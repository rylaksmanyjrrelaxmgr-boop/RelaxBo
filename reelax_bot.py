#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
بوت ريلاكس مانيجر - النسخة الكاملة النهائية (توقيت مكة المكرمة مع تخزين UTC)
جميع الأزرار تعمل - تم إصلاح زر قنوات البوت
دعم الوكيل اختياري، توكن عبر متغيرات البيئة
تم تعديل دالة add_points لحل مشكلة offset-naive/aware
تم إضافة أمر /sendcode لإرسال كود البوت كملف
تم إضافة إدارة صلاحية /sendcode عبر قاعدة البيانات
تم إضافة زر في لوحة الأدمن لإدارة صلاحية /sendcode
تم إضافة اللغات: الفرنسية والتركية والصينية والروسية
تم إضافة زر حذف جميع تذاكر الدعم في لوحة الأدمن
"""

import nest_asyncio
nest_asyncio.apply()

import asyncio
import aiosqlite
import random
import re
import shutil
import json
import logging
import os
import sys
import time as time_module
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict, deque
from typing import Optional, Dict, List, Tuple, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, BotCommand, LabeledPrice, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, Defaults, ChatMemberHandler, PreCheckoutQueryHandler
from telegram.error import TimedOut, NetworkError, BadRequest, Forbidden
from telegram.request import HTTPXRequest
import httpx
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID", "8290212138"))
BOT_NAME = os.getenv("BOT_NAME", "ريلاكس مانيجر - @Reelaaaxbot")
BOT_USERNAME = os.getenv("BOT_USERNAME", "Reelaaaxbot")
USE_PROXY = os.getenv("USE_PROXY", "False").lower() == "true"
PROXY_URL = os.getenv("PROXY_URL", "http://127.0.0.1:10809")

if not TOKEN:
    raise ValueError("❌ لم يتم العثور على BOT_TOKEN")

# ==================== دالة تحويل التاريخ إلى naive UTC ====================
def to_naive(dt):
    """تحويل أي datetime إلى naive UTC (بدون منطقة زمنية)"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        # إذا كان التاريخ aware، نحوله إلى UTC ثم نزيل معلومات المنطقة الزمنية
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

# ==================== توقيت UTC وتوقيت مكة (بدون timezone) ====================
def utc_now():
    """توقيت UTC الحالي (naive) - يستخدم للتخزين والمقارنات"""
    return datetime.utcnow()

def mecca_now():
    """توقيت مكة الحالي = UTC+3 (naive) - يستخدم فقط للعرض والعمليات التي تتطلب توقيت مكة"""
    return datetime.utcnow() + timedelta(hours=3)

def utc_now_iso():
    return utc_now().isoformat()

def mecca_now_iso():
    return mecca_now().isoformat()

# ==================== إعدادات التسجيل ====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log", encoding='utf-8'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
defaults = Defaults(parse_mode="HTML")
DB_PATH = Path("bot_data.db")
BACKUP_DIR = Path("backups")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
PAGE_SIZE = 10

# ==================== دوال مساعدة ====================
def escape_html(text: str) -> str:
    if not text: return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def safe_int_convert(val):
    try:
        return int(val) if val is not None else None
    except:
        return None

def parse_days_of_week_safe(days_str):
    if not days_str: return []
    try: return json.loads(days_str)
    except: return []

def parse_dates_safe(dates_str):
    if not dates_str: return []
    try: return json.loads(dates_str)
    except: return []

def parse_time_safe(time_str):
    if not time_str: return None
    try:
        parts = time_str.split(':')
        return (int(parts[0]), int(parts[1]))
    except: return None

def contains_link(text):
    patterns = [r'https?://\S+', r'www\.\S+', r't\.me/\S+', r'telegram\.me/\S+']
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)

def contains_mention(text):
    return bool(re.search(r'@\w+', text))

def get_ram_usage():
    try:
        import psutil
        mem = psutil.virtual_memory()
        return {'total': round(mem.total/(1024**3),1), 'used': round(mem.used/(1024**3),1), 'percent': mem.percent}
    except: return {'total': 0, 'used': 0, 'percent': 0}

async def log_activity(action: str, details: str):
    try:
        with open("logs.txt", "a", encoding="utf-8", errors='replace') as f:
            f.write(f"[{mecca_now().strftime('%Y-%m-%d %H:%M:%S')}] {action}: {details}\n")
    except: pass

# ==================== Connection Pool مع FOREIGN KEYS ====================
class DatabasePool:
    def __init__(self, db_path: Path, max_connections: int = 10):
        self.db_path = db_path
        self.max_connections = max_connections
        self._pool = asyncio.Queue(max_connections)
        self._initialized = False

    async def initialize(self):
        if self._initialized: return
        for _ in range(self.max_connections):
            conn = await aiosqlite.connect(self.db_path)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys = ON")
            await self._pool.put(conn)
        self._initialized = True
        logger.info(f"✅ Pool قاعدة البيانات بـ {self.max_connections} اتصال (foreign_keys=ON)")

    async def get_connection(self):
        if not self._initialized: await self.initialize()
        return await self._pool.get()

    async def return_connection(self, conn):
        await self._pool.put(conn)

    async def close_all(self):
        while not self._pool.empty():
            conn = await self._pool.get()
            await conn.close()

db_pool = DatabasePool(DB_PATH)

async def get_db(): return await db_pool.get_connection()
async def return_db(conn): await db_pool.return_connection(conn)

# ==================== ذاكرة مؤقتة ====================
_admins_cache = {}
_ADMINS_CACHE_TTL = 600
user_language = {}
_user_language_lock = asyncio.Lock()
_user_messages_times = defaultdict(lambda: deque(maxlen=10))
_channel_failure_count = defaultdict(int)
_channel_failure_lock = asyncio.Lock()
user_sessions = {}

# ==================== نظام اللغة (عربي/إنجليزي/فرنسي/تركي/صيني/روسي) ====================
LANGUAGES = {
    'ar': {
        'main_title': "🌿 **{}**\n━━━━━━━━━━━━━━━━\n👤 معرفك: `{}`\n👥 مجموعاتي: {}\n📦 الاشتراك: {}\n📡 القناة النشطة: {}\n📝 منشورات غير منشورة: {}\n⚙️ النشر التلقائي: {}",
        'no_channels': "❌ لا توجد قنوات. أضف قناة أولاً.",
        'channel_error': "⚠️ حدث خطأ في القناة.",
        'subscribed': "✅ مفعل", 'not_subscribed': "❌ غير مفعل", 'auto_on': "🟢 مفعل", 'auto_off': "🔴 معطل",
        'add_channel': "➕ إضافة قناة", 'my_channels': "📡 قنواتي", 'add_15_posts': "📥 إضافة 15 منشوراً",
        'publish_one': "📤 نشر واحد", 'my_posts_btn': "📝 منشوراتي", 'recycle': "♻️ إعادة تدوير",
        'my_stats_btn': "📊 إحصائياتي", 'my_groups_btn': "👥 مجموعاتي", 'stats_btn': "📈 متبقي",
        'settings_btn': "⚙️ الإعدادات", 'schedule_btn': "📅 الجدولة", 'security_btn': "🔐 الأمان",
        'my_rank_btn': "⭐ رتبتي", 'top_10_btn': "🏆 أفضل 10", 'schedule_post_btn': "📅 جدولة منشور",
        'help_btn': "❓ المساعدة", 'trial_btn': "🎁 تجربة مجانية", 'subscribe_btn': "💎 الاشتراك",
        'developer_btn': "👨‍💻 المطور", 'language_btn': "🌐 اللغة", 'support_btn': "🛟 الدعم",
        'add_to_group': "➕ أضف البوت لمجموعة", 'admin_panel': "👑 لوحة الأدمن", 'back': "🔙 رجوع",
        'welcome': "🌐 اختر لغتك / Choose your language:", 'lang_set': "✅ تم تغيير اللغة",
        'group_only': "⚠️ هذا الأمر يعمل فقط في المجموعات.", 'admin_only': "🔒 هذا الأمر للمشرفين فقط!",
        'send_channel_id': "📢 أرسل معرف القناة (مثال: @username أو -100123456789)",
        'channel_added': "✅ تم إضافة القناة {}\n(تأكد من أن البوت مشرف فيها).", 'channel_exists': "⚠️ القناة موجودة مسبقاً.",
        'no_channels_list': "📭 لا توجد قنوات مسجلة.", 'channels_list': "📡 قنواتك:",
        'channel_deleted': "✅ تم حذف القناة.", 'delete_failed': "❌ فشل الحذف.",
        'no_posts': "📭 لا توجد منشورات في هذه القناة.", 'post_published': "✅ تم النشر بنجاح.",
        'publish_error': "❌ فشل النشر: {}", 'stats': "📊 **إحصائياتك**\n━━━━━━━━━━━━━━━━\n📡 القنوات: {}\n📝 إجمالي المنشورات: {}\n📤 غير منشورة: {}\n👥 المجموعات: {}\n⚙️ النشر التلقائي: {}",
        'settings': "⚙️ **الإعدادات**\nاختر الإعداد المطلوب:", 'enabled': "✅ مفعل", 'disabled': "❌ معطل",
        'auto_toggled': "✅ تم {} النشر التلقائي.", 'recycled': "♻️ تم إعادة تعيين جميع المنشورات كغير منشورة.",
        'my_posts_title': "📝 **منشوراتي** (آخر 10):", 'confirm_delete': "⚠️ هل أنت متأكد من حذف جميع المنشورات؟",
        'deleted_all': "✅ تم حذف جميع المنشورات.", 'trial_used': "⚠️ لقد استخدمت نسختك التجريبية مسبقاً.",
        'already_subscribed': "✅ لديك اشتراك مفعل بالفعل.", 'trial': "🎉 **تم تفعيل النسخة التجريبية لمدة 30 يوماً!**\nاستمتع بجميع الميزات.",
        'subscribe': "💎 **الاشتراك**\nاختر الباقة المناسبة:\n⭐ 1 يوم - 5 نجوم\n⭐ 2 يوم - 9 نجوم\n⭐ شهر (30) - 50 نجمة\n⭐ 3 أشهر - 120 نجمة",
        'help': "📖 **المساعدة**\n\nالأوامر المتاحة:\n/start - القائمة الرئيسية\n/syncgroup - تفعيل البوت في المجموعة\n/security - إعدادات الأمان\n/trial - تجربة مجانية\n/subscribe - الاشتراك\n/rank - رتبتك\n/top - أفضل 10\n/panel - لوحة تحكم المجموعة\n/language - تغيير اللغة\n/support - الدعم\n/help - هذه المساعدة",
        'security_main': "🔐 **إعدادات الأمان**\nأرسل معرف المجموعة (مثال: @username أو -100123456789)\nأو استخدم /syncgroup أولاً.",
        'not_admin': "❌ لست مشرفاً في تلك المجموعة.", 'updated': "✅ تم التحديث.",
        'group_settings_title': "🔐 إعدادات الأمان - {}", 'links': "الروابط", 'mentions': "المعرفات",
        'banned_words': "كلمات محظورة", 'warn': "تحذير", 'slow_mode': "وضع بطيء",
        'welcome_msg': "الترحيب", 'goodbye_msg': "الوداع", 'no_groups': "📭 لا توجد مجموعات مسجلة.\nأضف البوت إلى مجموعة واستخدم /syncgroup.",
        'schedule_settings': "📅 **إعدادات الجدولة**\nالحالي: {}", 'interval_minutes': "⏱️ نشر كل {} دقيقة",
        'interval_hours': "⏱️ نشر كل {} ساعة", 'interval_days': "⏱️ نشر كل {} يوم",
        'days_week': "📅 أيام الأسبوع: {}", 'specific_dates': "🗓️ تواريخ محددة: {}", 'nothing': "لا شيء",
        'send_minutes': "🕐 أرسل عدد الدقائق (1-1440):", 'send_hours': "🕒 أرسل عدد الساعات (1-24):",
        'send_days': "📆 أرسل عدد الأيام (1-30):", 'send_dates': "🗓️ أرسل التواريخ بصيغة YYYY-MM-DD مفصولة بفواصل\nمثال: 2025-12-31, 2026-01-01",
        'send_time': "⏰ أرسل وقت النشر بصيغة HH:MM (24 ساعة)\nمثال: 14:30", 'invalid_number': "❌ رقم غير صالح.",
        'invalid_date': "❌ تاريخ غير صالح: {}\nاستخدم YYYY-MM-DD", 'invalid_time': "❌ وقت غير صالح. استخدم HH:MM",
        'dates_saved': "✅ تم حفظ {} تاريخاً.", 'days_saved': "✅ تم حفظ أيام الأسبوع.",
        'interval_set': "✅ تم ضبط النشر كل {}", 'cancelled': "❌ تم الإلغاء.", 'error': "⚠️ حدث خطأ.",
        'support_welcome': "🛟 **مركز الدعم**\nيمكنك إرسال رسالتك وسيتم الرد عليك في أقرب وقت.\nاستخدم الأزرار أدناه:",
        'support_help': "📖 **المساعدة**\nللتواصل مع الدعم، اكتب رسالتك وسنرد عليك خلال 24 ساعة.\nيمكنك متابعة تذكرتك عبر زر 'تذكرتي'.",
        'support_ticket': "📋 **تذكرتك**\nرقم التذكرة: #{}\nتاريخ الإنشاء: {}\nالحالة: معلقة.\nسيتم الرد عليك قريباً.",
        'support_no_ticket': "📭 ليس لديك تذاكر مفتوحة.\nلإنشاء تذكرة جديدة، أرسل رسالتك الآن.",
        'support_received': "✅ **تم استلام رسالتك**\n📋 رقم التذكرة: #{}\n📅 التاريخ: {}\nسيتم الرد عليك خلال 24 ساعة.",
        'support_notification': "📨 **تذكرة دعم جديدة**\n👤 المستخدم: {}\n🆔 ID: `{}`\n🎫 رقم التذكرة: #{}\n📅 الوقت: {}\n📝 الرسالة:\n```\n{}\n```\n💡 للرد: `/support_reply {} نص الرد`",
        'support_reply_sent': "✅ تم إرسال الرد إلى المستخدم {}", 'admin_users': "👥 المستخدمين النشطين",
        'admin_banned': "🚫 المستخدمين المحظورين", 'admin_channels': "📡 قنوات المستخدمين",
        'admin_banned_channels': "⛔ قنوات محظورة", 'admin_groups': "📊 المجموعات", 'admin_banned_groups': "🚷 مجموعات محظورة",
        'admin_bot_channels': "📢 قنوات البوت", 'admin_banned_bot_channels': "🚫 قنوات بوت محظورة",
        'monitor_users': "📂 مراقبة المستخدمين", 'general_stats': "📊 **إحصائيات عامة**", 'ram_status': "🖥️ **حالة الرام**",
        'publish_time': "⏱️ **وقت النشر العام** (بالدقائق)", 'backup_settings': "⚙️ **إعدادات النسخ الاحتياطي**",
        'locked': "🔒 تم قفل المجموعة.", 'unlocked': "🔓 تم فتح المجموعة.", 'ar': "العربية 🇸🇦", 'en': "English 🇬🇧",
        'restore_backup': "🔄 استعادة نسخة احتياطية", 'backup_created': "✅ تم إنشاء نسخة احتياطية: {}",
        'backup_restored': "✅ تم استعادة النسخة الاحتياطية: {}", 'no_backups': "📭 لا توجد نسخ احتياطية",
        'select_backup': "📋 اختر النسخة الاحتياطية لاستعادتها:", 'sec_banned_words': "🚫 كلمات محظورة",
        'manage_sendcode': "📁 صلاحية /sendcode", 'current_allowed_user': "👤 المستخدم المسموح له بـ /sendcode:\n{}",
        'set_new_sendcode_user': "➕ تعيين مستخدم جديد", 'send_sendcode_user_id': "📨 أرسل `user_id` الجديد الذي تريد السماح له باستخدام /sendcode.",
        'sendcode_user_set': "✅ تم تعيين المستخدم ذو المعرف `{}` للسماح باستخدام /sendcode.",
        'no_allowed_user': "❌ لم يتم تعيين أي مستخدم حتى الآن.",
        # إضافة مفاتيح للغات الجديدة في القائمة
        'fr': "Français 🇫🇷", 'tr': "Türkçe 🇹🇷", 'zh': "中文 🇨🇳", 'ru': "Русский 🇷🇺",
        # مفاتيح حذف التذاكر
        'delete_all_tickets': "🗑️ حذف جميع التذاكر",
        'confirm_delete_tickets': "⚠️ هل أنت متأكد من حذف جميع تذاكر الدعم؟ لا يمكن التراجع عن هذا الإجراء.",
        'tickets_deleted': "✅ تم حذف جميع تذاكر الدعم بنجاح.",
    },
    'en': {
        'main_title': "🌿 **{}**\n━━━━━━━━━━━━━━━━\n👤 Your ID: `{}`\n👥 My groups: {}\n📦 Subscription: {}\n📡 Active channel: {}\n📝 Unpublished posts: {}\n⚙️ Auto publish: {}",
        'no_channels': "❌ No channels. Add a channel first.", 'channel_error': "⚠️ Channel error.",
        'subscribed': "✅ Active", 'not_subscribed': "❌ Inactive", 'auto_on': "🟢 On", 'auto_off': "🔴 Off",
        'add_channel': "➕ Add channel", 'my_channels': "📡 My channels", 'add_15_posts': "📥 Add 15 posts",
        'publish_one': "📤 Publish one", 'my_posts_btn': "📝 My posts", 'recycle': "♻️ Recycle",
        'my_stats_btn': "📊 My stats", 'my_groups_btn': "👥 My groups", 'stats_btn': "📈 Pending",
        'settings_btn': "⚙️ Settings", 'schedule_btn': "📅 Schedule", 'security_btn': "🔐 Security",
        'my_rank_btn': "⭐ My rank", 'top_10_btn': "🏆 Top 10", 'schedule_post_btn': "📅 Schedule post",
        'help_btn': "❓ Help", 'trial_btn': "🎁 Free trial", 'subscribe_btn': "💎 Subscribe",
        'developer_btn': "👨‍💻 Developer", 'language_btn': "🌐 Language", 'support_btn': "🛟 Support",
        'add_to_group': "➕ Add bot to group", 'admin_panel': "👑 Admin panel", 'back': "🔙 Back",
        'welcome': "🌐 Choose your language:", 'lang_set': "✅ Language changed", 'group_only': "⚠️ This command works only in groups.",
        'admin_only': "🔒 Only admins can use this!", 'send_channel_id': "📢 Send channel ID (e.g., @username or -100123456789)",
        'channel_added': "✅ Channel {} added.\n(Make sure I'm an admin there).", 'channel_exists': "⚠️ Channel already exists.",
        'no_channels_list': "📭 No channels registered.", 'channels_list': "📡 Your channels:",
        'channel_deleted': "✅ Channel deleted.", 'delete_failed': "❌ Deletion failed.", 'no_posts': "📭 No posts in this channel.",
        'post_published': "✅ Post published.", 'publish_error': "❌ Publish failed: {}",
        'stats': "📊 **Your stats**\n━━━━━━━━━━━━━━━━\n📡 Channels: {}\n📝 Total posts: {}\n📤 Unpublished: {}\n👥 Groups: {}\n⚙️ Auto publish: {}",
        'settings': "⚙️ **Settings**\nChoose an option:", 'enabled': "✅ Enabled", 'disabled': "❌ Disabled",
        'auto_toggled': "✅ Auto publish is now {}.", 'recycled': "♻️ All posts marked as unpublished.",
        'my_posts_title': "📝 **My posts** (last 10):", 'confirm_delete': "⚠️ Are you sure you want to delete all posts?",
        'deleted_all': "✅ All posts deleted.", 'trial_used': "⚠️ You have already used your free trial.",
        'already_subscribed': "✅ You already have an active subscription.", 'trial': "🎉 **Free trial activated for 30 days!**\nEnjoy all features.",
        'subscribe': "💎 **Subscribe**\nChoose a plan:\n⭐ 1 day - 5 stars\n⭐ 2 days - 9 stars\n⭐ 1 month (30) - 50 stars\n⭐ 3 months - 120 stars",
        'help': "📖 **Help**\n\nAvailable commands:\n/start - Main menu\n/syncgroup - Activate bot in group\n/security - Security settings\n/trial - Free trial\n/subscribe - Subscribe\n/rank - Your rank\n/top - Top 10\n/panel - Group control panel\n/language - Change language\n/support - Support\n/help - This help",
        'security_main': "🔐 **Security settings**\nSend group ID (e.g., @username or -100123456789)\nOr use /syncgroup first.",
        'not_admin': "❌ You are not an admin in that group.", 'updated': "✅ Updated.",
        'group_settings_title': "🔐 Security settings - {}", 'links': "Links", 'mentions': "Mentions",
        'banned_words': "Banned words", 'warn': "Warning", 'slow_mode': "Slow mode",
        'welcome_msg': "Welcome", 'goodbye_msg': "Goodbye", 'no_groups': "📭 No groups registered.\nAdd bot to a group and use /syncgroup.",
        'schedule_settings': "📅 **Schedule settings**\nCurrent: {}", 'interval_minutes': "⏱️ Every {} minute(s)",
        'interval_hours': "⏱️ Every {} hour(s)", 'interval_days': "⏱️ Every {} day(s)", 'days_week': "📅 Week days: {}",
        'specific_dates': "🗓️ Specific dates: {}", 'nothing': "None", 'send_minutes': "🕐 Send minutes (1-1440):",
        'send_hours': "🕒 Send hours (1-24):", 'send_days': "📆 Send days (1-30):",
        'send_dates': "🗓️ Send dates as YYYY-MM-DD separated by commas\ne.g., 2025-12-31, 2026-01-01",
        'send_time': "⏰ Send publish time as HH:MM (24h)\ne.g., 14:30", 'invalid_number': "❌ Invalid number.",
        'invalid_date': "❌ Invalid date: {}\nUse YYYY-MM-DD", 'invalid_time': "❌ Invalid time. Use HH:MM",
        'dates_saved': "✅ {} dates saved.", 'days_saved': "✅ Week days saved.", 'interval_set': "✅ Interval set to {}",
        'cancelled': "❌ Cancelled.", 'error': "⚠️ An error occurred.",
        'support_welcome': "🛟 **Support Center**\nSend your message and we will reply as soon as possible.\nUse the buttons below:",
        'support_help': "📖 **Help**\nTo contact support, send your message and we will reply within 24 hours.\nYou can track your ticket via 'My Ticket' button.",
        'support_ticket': "📋 **Your ticket**\nTicket #: {}\nCreated at: {}\nStatus: pending.\nWe will reply soon.",
        'support_no_ticket': "📭 You have no open tickets.\nTo create a new ticket, send your message now.",
        'support_received': "✅ **Your message has been received**\n📋 Ticket #: {}\n📅 Time: {}\nWe will reply within 24 hours.",
        'support_notification': "📨 **New support ticket**\n👤 User: {}\n🆔 ID: `{}`\n🎫 Ticket #: {}\n📅 Time: {}\n📝 Message:\n```\n{}\n```\n💡 Reply: `/support_reply {} message`",
        'support_reply_sent': "✅ Reply sent to user {}", 'admin_users': "👥 Active users", 'admin_banned': "🚫 Banned users",
        'admin_channels': "📡 User channels", 'admin_banned_channels': "⛔ Banned channels", 'admin_groups': "📊 Groups",
        'admin_banned_groups': "🚷 Banned groups", 'admin_bot_channels': "📢 Bot channels", 'admin_banned_bot_channels': "🚫 Banned bot channels",
        'monitor_users': "📂 User monitoring", 'general_stats': "📊 **General stats**", 'ram_status': "🖥️ **RAM status**",
        'publish_time': "⏱️ **Global publish interval** (minutes)", 'backup_settings': "⚙️ **Backup settings**",
        'locked': "🔒 Group locked.", 'unlocked': "🔓 Group unlocked.", 'ar': "العربية 🇸🇦", 'en': "English 🇬🇧",
        'restore_backup': "🔄 Restore backup", 'backup_created': "✅ Backup created: {}", 'backup_restored': "✅ Backup restored: {}",
        'no_backups': "📭 No backups available", 'select_backup': "📋 Select backup to restore:", 'sec_banned_words': "🚫 Banned words",
        'manage_sendcode': "📁 /sendcode permission", 'current_allowed_user': "👤 User allowed to use /sendcode:\n{}",
        'set_new_sendcode_user': "➕ Set new user", 'send_sendcode_user_id': "📨 Send the new `user_id` to allow using /sendcode.",
        'sendcode_user_set': "✅ User ID `{}` is now allowed to use /sendcode.",
        'no_allowed_user': "❌ No user has been set yet.",
        'fr': "Français 🇫🇷", 'tr': "Türkçe 🇹🇷", 'zh': "中文 🇨🇳", 'ru': "Русский 🇷🇺",
        'delete_all_tickets': "🗑️ Delete all tickets",
        'confirm_delete_tickets': "⚠️ Are you sure you want to delete all support tickets? This action cannot be undone.",
        'tickets_deleted': "✅ All support tickets have been deleted successfully.",
    },
    'fr': {
        'main_title': "🌿 **{}**\n━━━━━━━━━━━━━━━━\n👤 Votre ID: `{}`\n👥 Mes groupes: {}\n📦 Abonnement: {}\n📡 Chaîne active: {}\n📝 Publications non publiées: {}\n⚙️ Publication auto: {}",
        'no_channels': "❌ Aucune chaîne. Ajoutez une chaîne d'abord.",
        'channel_error': "⚠️ Erreur de chaîne.",
        'subscribed': "✅ Actif", 'not_subscribed': "❌ Inactif", 'auto_on': "🟢 Activé", 'auto_off': "🔴 Désactivé",
        'add_channel': "➕ Ajouter une chaîne", 'my_channels': "📡 Mes chaînes", 'add_15_posts': "📥 Ajouter 15 messages",
        'publish_one': "📤 Publier un", 'my_posts_btn': "📝 Mes messages", 'recycle': "♻️ Recycler",
        'my_stats_btn': "📊 Mes statistiques", 'my_groups_btn': "👥 Mes groupes", 'stats_btn': "📈 En attente",
        'settings_btn': "⚙️ Paramètres", 'schedule_btn': "📅 Planification", 'security_btn': "🔐 Sécurité",
        'my_rank_btn': "⭐ Mon rang", 'top_10_btn': "🏆 Top 10", 'schedule_post_btn': "📅 Planifier un message",
        'help_btn': "❓ Aide", 'trial_btn': "🎁 Essai gratuit", 'subscribe_btn': "💎 S'abonner",
        'developer_btn': "👨‍💻 Développeur", 'language_btn': "🌐 Langue", 'support_btn': "🛟 Support",
        'add_to_group': "➕ Ajouter le bot au groupe", 'admin_panel': "👑 Panneau d'admin", 'back': "🔙 Retour",
        'welcome': "🌐 Choisissez votre langue :", 'lang_set': "✅ Langue modifiée",
        'group_only': "⚠️ Cette commande fonctionne uniquement dans les groupes.",
        'admin_only': "🔒 Réservé aux administrateurs !",
        'send_channel_id': "📢 Envoyez l'ID de la chaîne (ex: @username ou -100123456789)",
        'channel_added': "✅ Chaîne {} ajoutée.\n(Assurez-vous que je suis administrateur).",
        'channel_exists': "⚠️ La chaîne existe déjà.",
        'no_channels_list': "📭 Aucune chaîne enregistrée.",
        'channels_list': "📡 Vos chaînes :",
        'channel_deleted': "✅ Chaîne supprimée.",
        'delete_failed': "❌ Échec de la suppression.",
        'no_posts': "📭 Aucun message dans cette chaîne.",
        'post_published': "✅ Message publié.",
        'publish_error': "❌ Échec de publication : {}",
        'stats': "📊 **Vos statistiques**\n━━━━━━━━━━━━━━━━\n📡 Chaînes : {}\n📝 Total messages : {}\n📤 Non publiés : {}\n👥 Groupes : {}\n⚙️ Publication auto : {}",
        'settings': "⚙️ **Paramètres**\nChoisissez une option :",
        'enabled': "✅ Activé", 'disabled': "❌ Désactivé",
        'auto_toggled': "✅ La publication automatique est maintenant {}.", 'recycled': "♻️ Tous les messages marqués comme non publiés.",
        'my_posts_title': "📝 **Mes messages** (10 derniers) :",
        'confirm_delete': "⚠️ Êtes-vous sûr de vouloir supprimer tous les messages ?",
        'deleted_all': "✅ Tous les messages supprimés.",
        'trial_used': "⚠️ Vous avez déjà utilisé votre essai gratuit.",
        'already_subscribed': "✅ Vous avez déjà un abonnement actif.",
        'trial': "🎉 **Essai gratuit activé pour 30 jours !**\nProfitez de toutes les fonctionnalités.",
        'subscribe': "💎 **S'abonner**\nChoisissez une formule :\n⭐ 1 jour - 5 étoiles\n⭐ 2 jours - 9 étoiles\n⭐ 1 mois (30) - 50 étoiles\n⭐ 3 mois - 120 étoiles",
        'help': "📖 **Aide**\n\nCommandes disponibles :\n/start - Menu principal\n/syncgroup - Activer le bot dans le groupe\n/security - Paramètres de sécurité\n/trial - Essai gratuit\n/subscribe - S'abonner\n/rank - Votre rang\n/top - Top 10\n/panel - Panneau de contrôle du groupe\n/language - Changer la langue\n/support - Support\n/help - Cette aide",
        'security_main': "🔐 **Paramètres de sécurité**\nEnvoyez l'ID du groupe (ex: @username ou -100123456789)\nOu utilisez /syncgroup d'abord.",
        'not_admin': "❌ Vous n'êtes pas administrateur de ce groupe.",
        'updated': "✅ Mis à jour.",
        'group_settings_title': "🔐 Paramètres de sécurité - {}",
        'links': "Liens", 'mentions': "Mentions", 'banned_words': "Mots interdits", 'warn': "Avertir",
        'slow_mode': "Mode lent", 'welcome_msg': "Accueil", 'goodbye_msg': "Au revoir",
        'no_groups': "📭 Aucun groupe enregistré.\nAjoutez le bot à un groupe et utilisez /syncgroup.",
        'schedule_settings': "📅 **Paramètres de planification**\nActuel : {}",
        'interval_minutes': "⏱️ Toutes les {} minute(s)", 'interval_hours': "⏱️ Toutes les {} heure(s)",
        'interval_days': "⏱️ Tous les {} jour(s)", 'days_week': "📅 Jours de la semaine : {}",
        'specific_dates': "🗓️ Dates spécifiques : {}", 'nothing': "Rien",
        'send_minutes': "🕐 Envoyez le nombre de minutes (1-1440) :",
        'send_hours': "🕒 Envoyez le nombre d'heures (1-24) :",
        'send_days': "📆 Envoyez le nombre de jours (1-30) :",
        'send_dates': "🗓️ Envoyez les dates au format YYYY-MM-DD séparées par des virgules\nex: 2025-12-31, 2026-01-01",
        'send_time': "⏰ Envoyez l'heure de publication au format HH:MM (24h)\nex: 14:30",
        'invalid_number': "❌ Nombre invalide.",
        'invalid_date': "❌ Date invalide : {}\nUtilisez YYYY-MM-DD",
        'invalid_time': "❌ Heure invalide. Utilisez HH:MM",
        'dates_saved': "✅ {} dates enregistrées.",
        'days_saved': "✅ Jours de la semaine enregistrés.",
        'interval_set': "✅ Intervalle réglé sur {}",
        'cancelled': "❌ Annulé.",
        'error': "⚠️ Une erreur est survenue.",
        'support_welcome': "🛟 **Centre de support**\nEnvoyez votre message, nous vous répondrons dès que possible.\nUtilisez les boutons ci-dessous :",
        'support_help': "📖 **Aide**\nPour contacter le support, envoyez votre message, nous vous répondrons sous 24h.\nSuivez votre ticket via le bouton 'Mon ticket'.",
        'support_ticket': "📋 **Votre ticket**\nTicket n° : {}\nCréé le : {}\nStatut : en attente.\nNous vous répondrons bientôt.",
        'support_no_ticket': "📭 Vous n'avez aucun ticket ouvert.\nPour créer un nouveau ticket, envoyez votre message maintenant.",
        'support_received': "✅ **Votre message a été reçu**\n📋 Ticket n° : {}\n📅 Heure : {}\nNous vous répondrons sous 24h.",
        'support_notification': "📨 **Nouveau ticket de support**\n👤 Utilisateur : {}\n🆔 ID : `{}`\n🎫 Ticket n° : #{}\n📅 Heure : {}\n📝 Message :\n```\n{}\n```\n💡 Répondre : `/support_reply {} message`",
        'support_reply_sent': "✅ Réponse envoyée à l'utilisateur {}",
        'admin_users': "👥 Utilisateurs actifs", 'admin_banned': "🚫 Utilisateurs bannis",
        'admin_channels': "📡 Chaînes des utilisateurs", 'admin_banned_channels': "⛔ Chaînes bannies",
        'admin_groups': "📊 Groupes", 'admin_banned_groups': "🚷 Groupes bannis",
        'admin_bot_channels': "📢 Chaînes du bot", 'admin_banned_bot_channels': "🚫 Chaînes de bot bannies",
        'monitor_users': "📂 Surveillance des utilisateurs",
        'general_stats': "📊 **Statistiques générales**", 'ram_status': "🖥️ **État de la RAM**",
        'publish_time': "⏱️ **Intervalle de publication global** (minutes)",
        'backup_settings': "⚙️ **Paramètres de sauvegarde**",
        'locked': "🔒 Groupe verrouillé.", 'unlocked': "🔓 Groupe déverrouillé.",
        'ar': "العربية 🇸🇦", 'en': "English 🇬🇧", 'fr': "Français 🇫🇷", 'tr': "Türkçe 🇹🇷", 'zh': "中文 🇨🇳", 'ru': "Русский 🇷🇺",
        'restore_backup': "🔄 Restaurer une sauvegarde",
        'backup_created': "✅ Sauvegarde créée : {}", 'backup_restored': "✅ Sauvegarde restaurée : {}",
        'no_backups': "📭 Aucune sauvegarde disponible", 'select_backup': "📋 Choisissez la sauvegarde à restaurer :",
        'sec_banned_words': "🚫 Mots interdits",
        'manage_sendcode': "📁 Permission /sendcode",
        'current_allowed_user': "👤 Utilisateur autorisé à utiliser /sendcode :\n{}",
        'set_new_sendcode_user': "➕ Définir un nouvel utilisateur",
        'send_sendcode_user_id': "📨 Envoyez le nouvel `user_id` à autoriser à utiliser /sendcode.",
        'sendcode_user_set': "✅ L'utilisateur ID `{}` est maintenant autorisé à utiliser /sendcode.",
        'no_allowed_user': "❌ Aucun utilisateur n'a encore été défini.",
        'delete_all_tickets': "🗑️ Supprimer tous les tickets",
        'confirm_delete_tickets': "⚠️ Êtes-vous sûr de vouloir supprimer tous les tickets de support ? Cette action est irréversible.",
        'tickets_deleted': "✅ Tous les tickets de support ont été supprimés avec succès.",
    },
    'tr': {
        'main_title': "🌿 **{}**\n━━━━━━━━━━━━━━━━\n👤 ID'niz: `{}`\n👥 Gruplarım: {}\n📦 Abonelik: {}\n📡 Aktif kanal: {}\n📝 Yayınlanmamış gönderiler: {}\n⚙️ Otomatik yayın: {}",
        'no_channels': "❌ Kanal yok. Önce bir kanal ekleyin.",
        'channel_error': "⚠️ Kanal hatası.",
        'subscribed': "✅ Aktif", 'not_subscribed': "❌ Aktif değil", 'auto_on': "🟢 Açık", 'auto_off': "🔴 Kapalı",
        'add_channel': "➕ Kanal ekle", 'my_channels': "📡 Kanallarım", 'add_15_posts': "📥 15 gönderi ekle",
        'publish_one': "📤 Bir gönderi yayınla", 'my_posts_btn': "📝 Gönderilerim", 'recycle': "♻️ Geri dönüştür",
        'my_stats_btn': "📊 İstatistiklerim", 'my_groups_btn': "👥 Gruplarım", 'stats_btn': "📈 Bekleyen",
        'settings_btn': "⚙️ Ayarlar", 'schedule_btn': "📅 Zamanlama", 'security_btn': "🔐 Güvenlik",
        'my_rank_btn': "⭐ Sıralamam", 'top_10_btn': "🏆 İlk 10", 'schedule_post_btn': "📅 Gönderi zamanla",
        'help_btn': "❓ Yardım", 'trial_btn': "🎁 Ücretsiz deneme", 'subscribe_btn': "💎 Abone ol",
        'developer_btn': "👨‍💻 Geliştirici", 'language_btn': "🌐 Dil", 'support_btn': "🛟 Destek",
        'add_to_group': "➕ Botu gruba ekle", 'admin_panel': "👑 Yönetici paneli", 'back': "🔙 Geri",
        'welcome': "🌐 Dilinizi seçin:", 'lang_set': "✅ Dil değiştirildi",
        'group_only': "⚠️ Bu komut yalnızca gruplarda çalışır.",
        'admin_only': "🔒 Bu komutu yalnızca yöneticiler kullanabilir!",
        'send_channel_id': "📢 Kanal kimliğini gönderin (örn: @kullaniciadi veya -100123456789)",
        'channel_added': "✅ {} kanalı eklendi.\n(Botun burada yönetici olduğundan emin olun).",
        'channel_exists': "⚠️ Kanal zaten mevcut.",
        'no_channels_list': "📭 Kayıtlı kanal yok.",
        'channels_list': "📡 Kanallarınız:",
        'channel_deleted': "✅ Kanal silindi.",
        'delete_failed': "❌ Silme başarısız.",
        'no_posts': "📭 Bu kanalda gönderi yok.",
        'post_published': "✅ Gönderi yayınlandı.",
        'publish_error': "❌ Yayınlama başarısız: {}",
        'stats': "📊 **İstatistikleriniz**\n━━━━━━━━━━━━━━━━\n📡 Kanallar: {}\n📝 Toplam gönderi: {}\n📤 Yayınlanmamış: {}\n👥 Gruplar: {}\n⚙️ Otomatik yayın: {}",
        'settings': "⚙️ **Ayarlar**\nBir seçenek belirleyin:",
        'enabled': "✅ Etkin", 'disabled': "❌ Pasif",
        'auto_toggled': "✅ Otomatik yayınlama şimdi {}.", 'recycled': "♻️ Tüm gönderiler yayınlanmamış olarak işaretlendi.",
        'my_posts_title': "📝 **Gönderilerim** (son 10):",
        'confirm_delete': "⚠️ Tüm gönderileri silmek istediğinizden emin misiniz?",
        'deleted_all': "✅ Tüm gönderiler silindi.",
        'trial_used': "⚠️ Ücretsiz denemenizi zaten kullandınız.",
        'already_subscribed': "✅ Zaten aktif bir aboneliğiniz var.",
        'trial': "🎉 **30 günlük ücretsiz deneme aktifleştirildi!**\nTüm özelliklerin tadını çıkarın.",
        'subscribe': "💎 **Abone ol**\nBir plan seçin:\n⭐ 1 gün - 5 yıldız\n⭐ 2 gün - 9 yıldız\n⭐ 1 ay (30) - 50 yıldız\n⭐ 3 ay - 120 yıldız",
        'help': "📖 **Yardım**\n\nMevcut komutlar:\n/start - Ana menü\n/syncgroup - Botu grupta etkinleştir\n/security - Güvenlik ayarları\n/trial - Ücretsiz deneme\n/subscribe - Abone ol\n/rank - Sıralaman\n/top - İlk 10\n/panel - Grup kontrol paneli\n/language - Dili değiştir\n/support - Destek\n/help - Bu yardım",
        'security_main': "🔐 **Güvenlik ayarları**\nGrup kimliğini gönderin (örn: @kullaniciadi veya -100123456789)\nVeya önce /syncgroup kullanın.",
        'not_admin': "❌ Bu grupta yönetici değilsiniz.",
        'updated': "✅ Güncellendi.",
        'group_settings_title': "🔐 Güvenlik ayarları - {}",
        'links': "Bağlantılar", 'mentions': "Etiketler", 'banned_words': "Yasaklı kelimeler", 'warn': "Uyar",
        'slow_mode': "Yavaş mod", 'welcome_msg': "Karşılama", 'goodbye_msg': "Veda",
        'no_groups': "📭 Kayıtlı grup yok.\nBotu bir gruba ekleyin ve /syncgroup kullanın.",
        'schedule_settings': "📅 **Zamanlama ayarları**\nMevcut: {}",
        'interval_minutes': "⏱️ Her {} dakikada bir yayınla", 'interval_hours': "⏱️ Her {} saatte bir yayınla",
        'interval_days': "⏱️ Her {} günde bir yayınla", 'days_week': "📅 Haftanın günleri: {}",
        'specific_dates': "🗓️ Belirli tarihler: {}", 'nothing': "Hiçbiri",
        'send_minutes': "🕐 Dakika sayısını gönderin (1-1440):",
        'send_hours': "🕒 Saat sayısını gönderin (1-24):",
        'send_days': "📆 Gün sayısını gönderin (1-30):",
        'send_dates': "🗓️ Tarihleri YYYY-AA-GG formatında virgülle ayırarak gönderin\nÖrnek: 2025-12-31, 2026-01-01",
        'send_time': "⏰ Yayın saatini HH:DD formatında gönderin (24 saat)\nÖrnek: 14:30",
        'invalid_number': "❌ Geçersiz sayı.",
        'invalid_date': "❌ Geçersiz tarih: {}\nYYYY-AA-GG kullanın",
        'invalid_time': "❌ Geçersiz saat. HH:DD kullanın",
        'dates_saved': "✅ {} tarih kaydedildi.",
        'days_saved': "✅ Haftanın günleri kaydedildi.",
        'interval_set': "✅ Aralık {} olarak ayarlandı",
        'cancelled': "❌ İptal edildi.",
        'error': "⚠️ Bir hata oluştu.",
        'support_welcome': "🛟 **Destek Merkezi**\nMesajınızı gönderin, en kısa sürede size dönüş yapılacaktır.\nAşağıdaki butonları kullanın:",
        'support_help': "📖 **Yardım**\nDestekle iletişime geçmek için mesajınızı gönderin, 24 saat içinde size dönüş yapılacaktır.\nTicket'ınızı 'Ticket'ım' butonu ile takip edebilirsiniz.",
        'support_ticket': "📋 **Ticket'ınız**\nTicket #: {}\nOluşturulma tarihi: {}\nDurum: bekliyor.\nYakında size dönüş yapılacak.",
        'support_no_ticket': "📭 Açık ticket'ınız yok.\nYeni bir ticket oluşturmak için şimdi mesajınızı gönderin.",
        'support_received': "✅ **Mesajınız alındı**\n📋 Ticket #: {}\n📅 Zaman: {}\n24 saat içinde size dönüş yapılacaktır.",
        'support_notification': "📨 **Yeni destek ticket'i**\n👤 Kullanıcı: {}\n🆔 ID: `{}`\n🎫 Ticket #: #{}\n📅 Zaman: {}\n📝 Mesaj:\n```\n{}\n```\n💡 Yanıtla: `/support_reply {} mesaj`",
        'support_reply_sent': "✅ {} kullanıcısına yanıt gönderildi",
        'admin_users': "👥 Aktif kullanıcılar", 'admin_banned': "🚫 Yasaklı kullanıcılar",
        'admin_channels': "📡 Kullanıcı kanalları", 'admin_banned_channels': "⛔ Yasaklı kanallar",
        'admin_groups': "📊 Gruplar", 'admin_banned_groups': "🚷 Yasaklı gruplar",
        'admin_bot_channels': "📢 Bot kanalları", 'admin_banned_bot_channels': "🚫 Yasaklı bot kanalları",
        'monitor_users': "📂 Kullanıcı izleme",
        'general_stats': "📊 **Genel istatistikler**", 'ram_status': "🖥️ **RAM durumu**",
        'publish_time': "⏱️ **Küresel yayın aralığı** (dakika)",
        'backup_settings': "⚙️ **Yedekleme ayarları**",
        'locked': "🔒 Grup kilitlendi.", 'unlocked': "🔓 Grubun kilidi açıldı.",
        'ar': "العربية 🇸🇦", 'en': "English 🇬🇧", 'fr': "Français 🇫🇷", 'tr': "Türkçe 🇹🇷", 'zh': "中文 🇨🇳", 'ru': "Русский 🇷🇺",
        'restore_backup': "🔄 Yedekten geri yükle",
        'backup_created': "✅ Yedek oluşturuldu: {}", 'backup_restored': "✅ Yedek geri yüklendi: {}",
        'no_backups': "📭 Yedek mevcut değil", 'select_backup': "📋 Geri yüklenecek yedeği seçin:",
        'sec_banned_words': "🚫 Yasaklı kelimeler",
        'manage_sendcode': "📁 /sendcode izni",
        'current_allowed_user': "👤 /sendcode kullanmasına izin verilen kullanıcı:\n{}",
        'set_new_sendcode_user': "➕ Yeni kullanıcı belirle",
        'send_sendcode_user_id': "📨 /sendcode kullanmasına izin vermek istediğiniz yeni `user_id`'yi gönderin.",
        'sendcode_user_set': "✅ `{}` kimlikli kullanıcının artık /sendcode kullanmasına izin veriliyor.",
        'no_allowed_user': "❌ Henüz bir kullanıcı belirlenmedi.",
        'delete_all_tickets': "🗑️ Tüm ticket'ları sil",
        'confirm_delete_tickets': "⚠️ Tüm destek ticket'larını silmek istediğinizden emin misiniz? Bu işlem geri alınamaz.",
        'tickets_deleted': "✅ Tüm destek ticket'ları başarıyla silindi.",
    },
    'zh': {
        'main_title': "🌿 **{}**\n━━━━━━━━━━━━━━━━\n👤 您的ID: `{}`\n👥 我的群组: {}\n📦 订阅: {}\n📡 活跃频道: {}\n📝 未发布帖子: {}\n⚙️ 自动发布: {}",
        'no_channels': "❌ 没有频道。请先添加频道。",
        'channel_error': "⚠️ 频道错误。",
        'subscribed': "✅ 已激活", 'not_subscribed': "❌ 未激活", 'auto_on': "🟢 开启", 'auto_off': "🔴 关闭",
        'add_channel': "➕ 添加频道", 'my_channels': "📡 我的频道", 'add_15_posts': "📥 添加15条帖子",
        'publish_one': "📤 发布一条", 'my_posts_btn': "📝 我的帖子", 'recycle': "♻️ 回收",
        'my_stats_btn': "📊 我的统计", 'my_groups_btn': "👥 我的群组", 'stats_btn': "📈 待发布",
        'settings_btn': "⚙️ 设置", 'schedule_btn': "📅 定时", 'security_btn': "🔐 安全",
        'my_rank_btn': "⭐ 我的等级", 'top_10_btn': "🏆 前十名", 'schedule_post_btn': "📅 定时帖子",
        'help_btn': "❓ 帮助", 'trial_btn': "🎁 免费试用", 'subscribe_btn': "💎 订阅",
        'developer_btn': "👨‍💻 开发者", 'language_btn': "🌐 语言", 'support_btn': "🛟 支持",
        'add_to_group': "➕ 将机器人添加到群组", 'admin_panel': "👑 管理面板", 'back': "🔙 返回",
        'welcome': "🌐 选择您的语言:", 'lang_set': "✅ 语言已更改",
        'group_only': "⚠️ 此命令仅在群组中有效。",
        'admin_only': "🔒 只有管理员可以使用此命令！",
        'send_channel_id': "📢 发送频道ID（例如：@用户名 或 -100123456789）",
        'channel_added': "✅ 频道 {} 已添加。\n（请确保我是管理员）。",
        'channel_exists': "⚠️ 频道已存在。",
        'no_channels_list': "📭 没有注册的频道。",
        'channels_list': "📡 您的频道:",
        'channel_deleted': "✅ 频道已删除。",
        'delete_failed': "❌ 删除失败。",
        'no_posts': "📭 此频道中没有帖子。",
        'post_published': "✅ 帖子已发布。",
        'publish_error': "❌ 发布失败: {}",
        'stats': "📊 **您的统计**\n━━━━━━━━━━━━━━━━\n📡 频道: {}\n📝 总帖子: {}\n📤 未发布: {}\n👥 群组: {}\n⚙️ 自动发布: {}",
        'settings': "⚙️ **设置**\n选择一个选项:",
        'enabled': "✅ 启用", 'disabled': "❌ 禁用",
        'auto_toggled': "✅ 自动发布现已{}.", 'recycled': "♻️ 所有帖子标记为未发布。",
        'my_posts_title': "📝 **我的帖子**（最后10条）:",
        'confirm_delete': "⚠️ 您确定要删除所有帖子吗？",
        'deleted_all': "✅ 所有帖子已删除。",
        'trial_used': "⚠️ 您已经使用过免费试用。",
        'already_subscribed': "✅ 您已有有效订阅。",
        'trial': "🎉 **30天免费试用已激活！**\n享受所有功能。",
        'subscribe': "💎 **订阅**\n选择套餐:\n⭐ 1天 - 5星\n⭐ 2天 - 9星\n⭐ 1个月（30天） - 50星\n⭐ 3个月 - 120星",
        'help': "📖 **帮助**\n\n可用命令:\n/start - 主菜单\n/syncgroup - 在群组中激活机器人\n/security - 安全设置\n/trial - 免费试用\n/subscribe - 订阅\n/rank - 您的等级\n/top - 前十名\n/panel - 群组控制面板\n/language - 更改语言\n/support - 支持\n/help - 本帮助",
        'security_main': "🔐 **安全设置**\n发送群组ID（例如：@用户名 或 -100123456789）\n或先使用 /syncgroup。",
        'not_admin': "❌ 您不是该群组的管理员。",
        'updated': "✅ 已更新。",
        'group_settings_title': "🔐 安全设置 - {}",
        'links': "链接", 'mentions': "提及", 'banned_words': "禁用词", 'warn': "警告",
        'slow_mode': "慢速模式", 'welcome_msg': "欢迎", 'goodbye_msg': "告别",
        'no_groups': "📭 没有注册的群组。\n将机器人添加到群组并使用 /syncgroup。",
        'schedule_settings': "📅 **定时设置**\n当前: {}",
        'interval_minutes': "⏱️ 每 {} 分钟发布", 'interval_hours': "⏱️ 每 {} 小时发布",
        'interval_days': "⏱️ 每 {} 天发布", 'days_week': "📅 星期: {}",
        'specific_dates': "🗓️ 特定日期: {}", 'nothing': "无",
        'send_minutes': "🕐 发送分钟数 (1-1440):",
        'send_hours': "🕒 发送小时数 (1-24):",
        'send_days': "📆 发送天数 (1-30):",
        'send_dates': "🗓️ 发送日期，格式 YYYY-MM-DD，用逗号分隔\n例如: 2025-12-31, 2026-01-01",
        'send_time': "⏰ 发送发布时间，格式 HH:MM（24小时）\n例如: 14:30",
        'invalid_number': "❌ 无效数字。",
        'invalid_date': "❌ 无效日期: {}\n使用 YYYY-MM-DD",
        'invalid_time': "❌ 无效时间。使用 HH:MM",
        'dates_saved': "✅ 已保存 {} 个日期。",
        'days_saved': "✅ 已保存星期。",
        'interval_set': "✅ 间隔设置为 {}",
        'cancelled': "❌ 已取消。",
        'error': "⚠️ 发生错误。",
        'support_welcome': "🛟 **支持中心**\n发送您的消息，我们将尽快回复。\n使用以下按钮:",
        'support_help': "📖 **帮助**\n要联系支持，请发送您的消息，我们将在24小时内回复。\n您可以通过'我的工单'按钮跟踪您的工单。",
        'support_ticket': "📋 **您的工单**\n工单号: #{}\n创建时间: {}\n状态: 待处理。\n我们将尽快回复。",
        'support_no_ticket': "📭 您没有未处理的工单。\n要创建新工单，请立即发送您的消息。",
        'support_received': "✅ **您的消息已收到**\n📋 工单号: #{}\n📅 时间: {}\n我们将在24小时内回复。",
        'support_notification': "📨 **新的支持工单**\n👤 用户: {}\n🆔 ID: `{}`\n🎫 工单号: #{}\n📅 时间: {}\n📝 消息:\n```\n{}\n```\n💡 回复: `/support_reply {} 消息`",
        'support_reply_sent': "✅ 已向用户 {} 发送回复",
        'admin_users': "👥 活跃用户", 'admin_banned': "🚫 被封禁用户",
        'admin_channels': "📡 用户频道", 'admin_banned_channels': "⛔ 被封禁频道",
        'admin_groups': "📊 群组", 'admin_banned_groups': "🚷 被封禁群组",
        'admin_bot_channels': "📢 机器人频道", 'admin_banned_bot_channels': "🚫 被封禁机器人频道",
        'monitor_users': "📂 用户监控",
        'general_stats': "📊 **总体统计**", 'ram_status': "🖥️ **内存状态**",
        'publish_time': "⏱️ **全局发布间隔**（分钟）",
        'backup_settings': "⚙️ **备份设置**",
        'locked': "🔒 群组已锁定。", 'unlocked': "🔓 群组已解锁。",
        'ar': "العربية 🇸🇦", 'en': "English 🇬🇧", 'fr': "Français 🇫🇷", 'tr': "Türkçe 🇹🇷", 'zh': "中文 🇨🇳", 'ru': "Русский 🇷🇺",
        'restore_backup': "🔄 恢复备份",
        'backup_created': "✅ 备份已创建: {}", 'backup_restored': "✅ 备份已恢复: {}",
        'no_backups': "📭 没有可用备份", 'select_backup': "📋 选择要恢复的备份:",
        'sec_banned_words': "🚫 禁用词",
        'manage_sendcode': "📁 /sendcode 权限",
        'current_allowed_user': "👤 允许使用 /sendcode 的用户:\n{}",
        'set_new_sendcode_user': "➕ 设置新用户",
        'send_sendcode_user_id': "📨 发送新的 `user_id` 以允许其使用 /sendcode。",
        'sendcode_user_set': "✅ 用户ID `{}` 现在可以使用 /sendcode。",
        'no_allowed_user': "❌ 尚未设置任何用户。",
        'delete_all_tickets': "🗑️ 删除所有工单",
        'confirm_delete_tickets': "⚠️ 您确定要删除所有支持工单吗？此操作无法撤销。",
        'tickets_deleted': "✅ 所有支持工单已成功删除。",
    },
    'ru': {
        'main_title': "🌿 **{}**\n━━━━━━━━━━━━━━━━\n👤 Ваш ID: `{}`\n👥 Мои группы: {}\n📦 Подписка: {}\n📡 Активный канал: {}\n📝 Неопубликованные посты: {}\n⚙️ Автопубликация: {}",
        'no_channels': "❌ Нет каналов. Сначала добавьте канал.",
        'channel_error': "⚠️ Ошибка канала.",
        'subscribed': "✅ Активен", 'not_subscribed': "❌ Не активен", 'auto_on': "🟢 Вкл", 'auto_off': "🔴 Выкл",
        'add_channel': "➕ Добавить канал", 'my_channels': "📡 Мои каналы", 'add_15_posts': "📥 Добавить 15 постов",
        'publish_one': "📤 Опубликовать один", 'my_posts_btn': "📝 Мои посты", 'recycle': "♻️ Переработать",
        'my_stats_btn': "📊 Моя статистика", 'my_groups_btn': "👥 Мои группы", 'stats_btn': "📈 Ожидает",
        'settings_btn': "⚙️ Настройки", 'schedule_btn': "📅 Расписание", 'security_btn': "🔐 Безопасность",
        'my_rank_btn': "⭐ Мой ранг", 'top_10_btn': "🏆 Топ 10", 'schedule_post_btn': "📅 Запланировать пост",
        'help_btn': "❓ Помощь", 'trial_btn': "🎁 Бесплатная пробная версия", 'subscribe_btn': "💎 Подписаться",
        'developer_btn': "👨‍💻 Разработчик", 'language_btn': "🌐 Язык", 'support_btn': "🛟 Поддержка",
        'add_to_group': "➕ Добавить бота в группу", 'admin_panel': "👑 Панель администратора", 'back': "🔙 Назад",
        'welcome': "🌐 Выберите ваш язык:", 'lang_set': "✅ Язык изменён",
        'group_only': "⚠️ Эта команда работает только в группах.",
        'admin_only': "🔒 Только администраторы могут использовать это!",
        'send_channel_id': "📢 Отправьте ID канала (например: @username или -100123456789)",
        'channel_added': "✅ Канал {} добавлен.\n(Убедитесь, что я администратор).",
        'channel_exists': "⚠️ Канал уже существует.",
        'no_channels_list': "📭 Нет зарегистрированных каналов.",
        'channels_list': "📡 Ваши каналы:",
        'channel_deleted': "✅ Канал удалён.",
        'delete_failed': "❌ Не удалось удалить.",
        'no_posts': "📭 В этом канале нет постов.",
        'post_published': "✅ Пост опубликован.",
        'publish_error': "❌ Ошибка публикации: {}",
        'stats': "📊 **Ваша статистика**\n━━━━━━━━━━━━━━━━\n📡 Каналы: {}\n📝 Всего постов: {}\n📤 Неопубликовано: {}\n👥 Группы: {}\n⚙️ Автопубликация: {}",
        'settings': "⚙️ **Настройки**\nВыберите опцию:",
        'enabled': "✅ Включено", 'disabled': "❌ Выключено",
        'auto_toggled': "✅ Автопубликация теперь {}.", 'recycled': "♻️ Все посты отмечены как неопубликованные.",
        'my_posts_title': "📝 **Мои посты** (последние 10):",
        'confirm_delete': "⚠️ Вы уверены, что хотите удалить все посты?",
        'deleted_all': "✅ Все посты удалены.",
        'trial_used': "⚠️ Вы уже использовали бесплатную пробную версию.",
        'already_subscribed': "✅ У вас уже есть активная подписка.",
        'trial': "🎉 **Бесплатная пробная версия активирована на 30 дней!**\nНаслаждайтесь всеми функциями.",
        'subscribe': "💎 **Подписка**\nВыберите план:\n⭐ 1 день - 5 звёзд\n⭐ 2 дня - 9 звёзд\n⭐ 1 месяц (30) - 50 звёзд\n⭐ 3 месяца - 120 звёзд",
        'help': "📖 **Помощь**\n\nДоступные команды:\n/start - Главное меню\n/syncgroup - Активировать бота в группе\n/security - Настройки безопасности\n/trial - Бесплатная пробная версия\n/subscribe - Подписка\n/rank - Ваш ранг\n/top - Топ 10\n/panel - Панель управления группой\n/language - Сменить язык\n/support - Поддержка\n/help - Эта помощь",
        'security_main': "🔐 **Настройки безопасности**\nОтправьте ID группы (например: @username или -100123456789)\nИли сначала используйте /syncgroup.",
        'not_admin': "❌ Вы не администратор этой группы.",
        'updated': "✅ Обновлено.",
        'group_settings_title': "🔐 Настройки безопасности - {}",
        'links': "Ссылки", 'mentions': "Упоминания", 'banned_words': "Запрещённые слова", 'warn': "Предупреждение",
        'slow_mode': "Медленный режим", 'welcome_msg': "Приветствие", 'goodbye_msg': "Прощание",
        'no_groups': "📭 Нет зарегистрированных групп.\nДобавьте бота в группу и используйте /syncgroup.",
        'schedule_settings': "📅 **Настройки расписания**\nТекущее: {}",
        'interval_minutes': "⏱️ Публиковать каждые {} минут(ы)", 'interval_hours': "⏱️ Публиковать каждый(е) {} час(ов)",
        'interval_days': "⏱️ Публиковать каждый(е) {} день(дней)", 'days_week': "📅 Дни недели: {}",
        'specific_dates': "🗓️ Конкретные даты: {}", 'nothing': "Нет",
        'send_minutes': "🕐 Отправьте количество минут (1-1440):",
        'send_hours': "🕒 Отправьте количество часов (1-24):",
        'send_days': "📆 Отправьте количество дней (1-30):",
        'send_dates': "🗓️ Отправьте даты в формате ГГГГ-ММ-ДД, разделённые запятыми\nнапример: 2025-12-31, 2026-01-01",
        'send_time': "⏰ Отправьте время публикации в формате ЧЧ:ММ (24 часа)\nнапример: 14:30",
        'invalid_number': "❌ Неверное число.",
        'invalid_date': "❌ Неверная дата: {}\nИспользуйте ГГГГ-ММ-ДД",
        'invalid_time': "❌ Неверное время. Используйте ЧЧ:ММ",
        'dates_saved': "✅ {} дат сохранено.",
        'days_saved': "✅ Дни недели сохранены.",
        'interval_set': "✅ Интервал установлен на {}",
        'cancelled': "❌ Отменено.",
        'error': "⚠️ Произошла ошибка.",
        'support_welcome': "🛟 **Центр поддержки**\nОтправьте ваше сообщение, и мы ответим как можно скорее.\nИспользуйте кнопки ниже:",
        'support_help': "📖 **Помощь**\nЧтобы связаться с поддержкой, отправьте ваше сообщение, мы ответим в течение 24 часов.\nВы можете отслеживать ваш тикет через кнопку 'Мой тикет'.",
        'support_ticket': "📋 **Ваш тикет**\nТикет #: {}\nСоздан: {}\nСтатус: ожидание.\nМы скоро ответим.",
        'support_no_ticket': "📭 У вас нет открытых тикетов.\nЧтобы создать новый тикет, отправьте ваше сообщение сейчас.",
        'support_received': "✅ **Ваше сообщение получено**\n📋 Тикет #: {}\n📅 Время: {}\nМы ответим в течение 24 часов.",
        'support_notification': "📨 **Новый тикет поддержки**\n👤 Пользователь: {}\n🆔 ID: `{}`\n🎫 Тикет #: #{}\n📅 Время: {}\n📝 Сообщение:\n```\n{}\n```\n💡 Ответить: `/support_reply {} сообщение`",
        'support_reply_sent': "✅ Ответ отправлен пользователю {}",
        'admin_users': "👥 Активные пользователи", 'admin_banned': "🚫 Заблокированные пользователи",
        'admin_channels': "📡 Каналы пользователей", 'admin_banned_channels': "⛔ Заблокированные каналы",
        'admin_groups': "📊 Группы", 'admin_banned_groups': "🚷 Заблокированные группы",
        'admin_bot_channels': "📢 Каналы бота", 'admin_banned_bot_channels': "🚫 Заблокированные каналы бота",
        'monitor_users': "📂 Мониторинг пользователей",
        'general_stats': "📊 **Общая статистика**", 'ram_status': "🖥️ **Состояние ОЗУ**",
        'publish_time': "⏱️ **Глобальный интервал публикации** (минуты)",
        'backup_settings': "⚙️ **Настройки резервного копирования**",
        'locked': "🔒 Группа заблокирована.", 'unlocked': "🔓 Группа разблокирована.",
        'ar': "العربية 🇸🇦", 'en': "English 🇬🇧", 'fr': "Français 🇫🇷", 'tr': "Türkçe 🇹🇷", 'zh': "中文 🇨🇳", 'ru': "Русский 🇷🇺",
        'restore_backup': "🔄 Восстановить из резервной копии",
        'backup_created': "✅ Резервная копия создана: {}", 'backup_restored': "✅ Резервная копия восстановлена: {}",
        'no_backups': "📭 Нет доступных резервных копий", 'select_backup': "📋 Выберите резервную копию для восстановления:",
        'sec_banned_words': "🚫 Запрещённые слова",
        'manage_sendcode': "📁 Разрешение /sendcode",
        'current_allowed_user': "👤 Пользователь, которому разрешено использовать /sendcode:\n{}",
        'set_new_sendcode_user': "➕ Установить нового пользователя",
        'send_sendcode_user_id': "📨 Отправьте новый `user_id`, которому вы хотите разрешить использовать /sendcode.",
        'sendcode_user_set': "✅ Пользователю с ID `{}` теперь разрешено использовать /sendcode.",
        'no_allowed_user': "❌ Пользователь ещё не установлен.",
        'delete_all_tickets': "🗑️ Удалить все тикеты",
        'confirm_delete_tickets': "⚠️ Вы уверены, что хотите удалить все тикеты поддержки? Это действие необратимо.",
        'tickets_deleted': "✅ Все тикеты поддержки успешно удалены.",
    }
}

def get_text(user_id, key, *args):
    lang = user_language.get(user_id, 'ar')
    text = LANGUAGES.get(lang, LANGUAGES['ar']).get(key, key)
    if args:
        try: return text.format(*args)
        except: return text
    return text

async def set_user_language(user_id: int, lang: str):
    async with _user_language_lock:
        user_language[user_id] = lang

# ==================== دوال قاعدة البيانات (جميع التواريخ مخزنة بصيغة UTC naive) ====================
async def init_db():
    conn = await get_db()
    try:
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, auto_publish INTEGER DEFAULT 1, banned INTEGER DEFAULT 0, trial_used INTEGER DEFAULT 0, subscription_end TEXT DEFAULT NULL)")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, channel_id TEXT, channel_name TEXT, created_at TIMESTAMP, banned INTEGER DEFAULT 0)")
        await conn.execute("CREATE TABLE IF NOT EXISTS posts (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_db_id INTEGER, text TEXT, media_type TEXT DEFAULT 'text', media_file_id TEXT, published INTEGER DEFAULT 0, created_at TIMESTAMP)")
        await conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        await conn.execute("CREATE TABLE IF NOT EXISTS group_replies (keyword TEXT PRIMARY KEY, reply TEXT)")
        await conn.execute("CREATE TABLE IF NOT EXISTS group_security (chat_id INTEGER PRIMARY KEY, delete_links INTEGER DEFAULT 0, delete_mentions INTEGER DEFAULT 0, warn_message INTEGER DEFAULT 1)")
        await conn.execute("CREATE TABLE IF NOT EXISTS bot_admins (user_id INTEGER PRIMARY KEY)")
        await conn.execute("CREATE TABLE IF NOT EXISTS bot_groups (chat_id INTEGER PRIMARY KEY, chat_name TEXT, username TEXT, added_by INTEGER, added_at TIMESTAMP, banned INTEGER DEFAULT 0)")
        await conn.execute("CREATE TABLE IF NOT EXISTS bot_channels (channel_id INTEGER PRIMARY KEY, channel_name TEXT, added_by INTEGER, added_at TIMESTAMP, banned INTEGER DEFAULT 0)")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_messages (user_id INTEGER, chat_id INTEGER, message_time TIMESTAMP, PRIMARY KEY (user_id, chat_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS users_cache (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_updated TEXT)")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_warnings (user_id INTEGER, chat_id INTEGER, warnings INTEGER DEFAULT 0, PRIMARY KEY(user_id, chat_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS banned_words (id INTEGER PRIMARY KEY AUTOINCREMENT, word TEXT, chat_id INTEGER, added_by INTEGER, added_at TIMESTAMP, UNIQUE(word, chat_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS hidden_owner_groups (chat_id INTEGER PRIMARY KEY, owner_id INTEGER, is_hidden INTEGER DEFAULT 1)")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_groups_link (user_id INTEGER, chat_id INTEGER, PRIMARY KEY(user_id, chat_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_levels (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, level INTEGER DEFAULT 1)")
        await conn.execute("CREATE TABLE IF NOT EXISTS support_tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, message TEXT, ticket_number INTEGER, status TEXT DEFAULT 'pending', created_at TIMESTAMP, replied INTEGER DEFAULT 0)")
        await conn.execute("CREATE TABLE IF NOT EXISTS chat_locks (chat_id INTEGER PRIMARY KEY, locked INTEGER DEFAULT 0, locked_at TIMESTAMP, locked_by INTEGER)")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schedule (
                channel_db_id INTEGER PRIMARY KEY,
                schedule_type TEXT DEFAULT 'interval_minutes',
                interval_minutes INTEGER DEFAULT 12,
                interval_hours INTEGER DEFAULT 0,
                interval_days INTEGER DEFAULT 0,
                days_of_week TEXT DEFAULT '',
                specific_dates TEXT DEFAULT '',
                publish_time TEXT DEFAULT '00:00',
                next_publish_date TEXT,
                FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS last_publish (
                channel_db_id INTEGER PRIMARY KEY,
                last_publish_time TIMESTAMP,
                FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                publish_time TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                fail_count INTEGER DEFAULT 0
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_time ON scheduled_posts(publish_time)")

        # جدول الصلاحيات لأمر sendcode
        await conn.execute("CREATE TABLE IF NOT EXISTS allowed_sendcode_user (id INTEGER PRIMARY KEY CHECK (id=1), user_id INTEGER)")

        cur = await conn.execute("PRAGMA table_info(group_security)")
        existing_cols = [row[1] for row in await cur.fetchall()]
        new_cols = {
            "slow_mode": "INTEGER DEFAULT 0", "slow_mode_seconds": "INTEGER DEFAULT 5",
            "welcome_enabled": "INTEGER DEFAULT 0", "welcome_text": "TEXT DEFAULT 'مرحباً {user} في {chat} 🤍'",
            "goodbye_enabled": "INTEGER DEFAULT 0", "goodbye_text": "TEXT DEFAULT 'وداعاً {user} 👋'",
            "delete_banned_words": "INTEGER DEFAULT 0"
        }
        for col, col_type in new_cols.items():
            if col not in existing_cols:
                try: await conn.execute(f"ALTER TABLE group_security ADD COLUMN {col} {col_type}")
                except: pass

        cur = await conn.execute("PRAGMA table_info(users)")
        user_cols = [row[1] for row in await cur.fetchall()]
        if "subscription_end" not in user_cols:
            try: await conn.execute("ALTER TABLE users ADD COLUMN subscription_end TEXT DEFAULT NULL")
            except: pass

        cur = await conn.execute("PRAGMA table_info(bot_groups)")
        group_cols = [row[1] for row in await cur.fetchall()]
        if "username" not in group_cols:
            try: await conn.execute("ALTER TABLE bot_groups ADD COLUMN username TEXT DEFAULT NULL")
            except: pass

        cur = await conn.execute("PRAGMA table_info(schedule)")
        schedule_cols = [row[1] for row in await cur.fetchall()]
        if "interval_hours" not in schedule_cols:
            try: await conn.execute("ALTER TABLE schedule ADD COLUMN interval_hours INTEGER DEFAULT 0")
            except: pass
        if "interval_days" not in schedule_cols:
            try: await conn.execute("ALTER TABLE schedule ADD COLUMN interval_days INTEGER DEFAULT 0")
            except: pass
        if "publish_time" not in schedule_cols:
            try: await conn.execute("ALTER TABLE schedule ADD COLUMN publish_time TEXT DEFAULT '00:00'")
            except: pass

        await conn.execute("INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)", (MAIN_ADMIN_ID,))
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('publish_interval', ?)", (str(12*60),))
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('updates_channel', 'zzimmiie')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('force_subscribe_enabled', '0')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('force_subscribe_channel', '')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_backup', '1')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_backup', '')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_ticket_number', '0')")

        next_date = (utc_now() + timedelta(minutes=1)).isoformat()
        await conn.execute("UPDATE schedule SET next_publish_date = ? WHERE next_publish_date IS NULL", (next_date,))
        await conn.commit()
    finally:
        await return_db(conn)
    logger.info("✅ قاعدة البيانات جاهزة (UTC + توقيت مكة للعرض)")

# دالة لحذف جميع تذاكر الدعم
async def db_delete_all_tickets() -> int:
    """حذف جميع التذاكر من قاعدة البيانات وإرجاع عدد التذاكر المحذوفة"""
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT COUNT(*) FROM support_tickets")
        count = (await cur.fetchone())[0]
        await conn.execute("DELETE FROM support_tickets")
        await conn.commit()
        await log_activity("TICKETS_DELETED", f"تم حذف {count} تذكرة")
        return count
    finally:
        await return_db(conn)

async def db_register_user(uid):
    conn = await get_db()
    try:
        await conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
        await conn.execute("INSERT OR IGNORE INTO users_cache (user_id, last_updated) VALUES (?, ?)", (uid, utc_now_iso()))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("USER_REGISTER", f"{uid}")

async def db_update_user_cache(uid, username=None, first_name=None):
    conn = await get_db()
    try:
        if username or first_name:
            await conn.execute("INSERT OR REPLACE INTO users_cache (user_id, username, first_name, last_updated) VALUES (?,?,?,?)",
                           (uid, username or "", first_name or "", utc_now_iso()))
            await conn.commit()
    finally:
        await return_db(conn)

async def db_is_banned(uid):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT banned FROM users WHERE user_id=?", (uid,))
        row = await cur.fetchone()
        return row[0] == 1 if row else False
    finally:
        await return_db(conn)

async def db_set_ban(uid, ban):
    conn = await get_db()
    try:
        await conn.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if ban else 0, uid))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("USER_BAN", f"{uid} → {'محظور' if ban else 'غير محظور'}")

async def db_auto_status(uid):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT auto_publish FROM users WHERE user_id=?", (uid,))
        row = await cur.fetchone()
        return row[0] == 1 if row else True
    finally:
        await return_db(conn)

async def db_set_auto(uid, en):
    conn = await get_db()
    try:
        await conn.execute("UPDATE users SET auto_publish=? WHERE user_id=?", (1 if en else 0, uid))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("AUTO_PUBLISH", f"{uid} → {'مفعل' if en else 'معطل'}")

async def db_add_channel(uid, channel_id, channel_name=""):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT id FROM user_channels WHERE user_id=? AND channel_id=?", (uid, channel_id))
        if await cur.fetchone():
            return None
        created_at = utc_now_iso()
        await conn.execute("INSERT INTO user_channels (user_id, channel_id, channel_name, created_at, banned) VALUES (?,?,?,?,0)",
                         (uid, channel_id, channel_name or channel_id, created_at))
        await conn.commit()
        cur = await conn.execute("SELECT id FROM user_channels WHERE user_id=? AND channel_id=?", (uid, channel_id))
        row = await cur.fetchone()
        ch_db_id = row[0] if row else None
        if ch_db_id:
            next_date = (utc_now() + timedelta(minutes=1)).isoformat()
            await conn.execute("INSERT OR REPLACE INTO schedule (channel_db_id, schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time, next_publish_date) VALUES (?, 'interval_minutes', 12, 0, 0, '', '', '00:00', ?)",
                             (ch_db_id, next_date))
        await conn.commit()
        await log_activity("CHANNEL_ADD", f"{uid} → {channel_id}")
        return ch_db_id
    finally:
        await return_db(conn)

async def db_get_channels(uid):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT id, channel_id, channel_name, banned FROM user_channels WHERE user_id=? ORDER BY created_at", (uid,))
        return await cur.fetchall()
    finally:
        await return_db(conn)

async def db_delete_channel_by_id(user_id: int, channel_db_id: int) -> bool:
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT 1 FROM user_channels WHERE id=? AND user_id=?", (channel_db_id, user_id))
        if await cur.fetchone():
            await conn.execute("DELETE FROM posts WHERE channel_db_id=?", (channel_db_id,))
            await conn.execute("DELETE FROM schedule WHERE channel_db_id=?", (channel_db_id,))
            await conn.execute("DELETE FROM last_publish WHERE channel_db_id=?", (channel_db_id,))
            await conn.execute("DELETE FROM user_channels WHERE id=? AND user_id=?", (channel_db_id, user_id))
            await conn.commit()
            await log_activity("CHANNEL_DELETE", f"{user_id} → {channel_db_id}")
            return True
        return False
    finally:
        await return_db(conn)

async def db_channel_exists(channel_db_id: int) -> bool:
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT 1 FROM user_channels WHERE id=?", (channel_db_id,))
        return await cur.fetchone() is not None
    finally:
        await return_db(conn)

async def db_get_channel_info(channel_db_id):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT channel_id, channel_name, banned FROM user_channels WHERE id=?", (channel_db_id,))
        return await cur.fetchone()
    finally:
        await return_db(conn)

async def db_is_channel_banned(channel_db_id):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT banned FROM user_channels WHERE id=?", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] == 1 if row else False
    finally:
        await return_db(conn)

async def db_set_channel_ban(channel_db_id, banned):
    conn = await get_db()
    try:
        await conn.execute("UPDATE user_channels SET banned=? WHERE id=?", (1 if banned else 0, channel_db_id))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("CHANNEL_BAN", f"{channel_db_id} → {'محظورة' if banned else 'غير محظورة'}")

async def db_save_post(channel_db_id, text, media_type='text', media_file_id=None):
    conn = await get_db()
    try:
        await conn.execute("INSERT INTO posts (channel_db_id, text, media_type, media_file_id, created_at) VALUES (?,?,?,?,?)",
                         (channel_db_id, text, media_type, media_file_id, utc_now_iso()))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("POST_SAVE", f"{channel_db_id}")

async def db_save_posts(channel_db_id, texts):
    saved = 0
    conn = await get_db()
    try:
        for t in texts:
            if t and t.strip():
                await conn.execute("INSERT INTO posts (channel_db_id, text, media_type, created_at) VALUES (?,?,?,?)",
                                 (channel_db_id, t, 'text', utc_now_iso()))
                saved += 1
        await conn.commit()
        next_date = (utc_now() + timedelta(minutes=1)).isoformat()
        await conn.execute("UPDATE schedule SET next_publish_date = ? WHERE channel_db_id = ?", (next_date, channel_db_id))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("POSTS_SAVE", f"{channel_db_id} → {saved}")
    return saved

async def db_get_next_post(channel_db_id, allow_recycle=True):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=?", (channel_db_id,))
        count = (await cur.fetchone())[0]
        if count == 0:
            return None
        cur = await conn.execute("SELECT id, text, media_type, media_file_id FROM posts WHERE channel_db_id=? AND published=0 ORDER BY id LIMIT 1", (channel_db_id,))
        row = await cur.fetchone()
        if row:
            return {'id': row[0], 'text': row[1], 'media_type': row[2], 'media_file_id': row[3]}
        if allow_recycle:
            await conn.execute("UPDATE posts SET published=0 WHERE channel_db_id=?", (channel_db_id,))
            await conn.commit()
            cur = await conn.execute("SELECT id, text, media_type, media_file_id FROM posts WHERE channel_db_id=? ORDER BY id LIMIT 1", (channel_db_id,))
            row = await cur.fetchone()
            if row:
                return {'id': row[0], 'text': row[1], 'media_type': row[2], 'media_file_id': row[3]}
        return None
    finally:
        await return_db(conn)

async def db_mark_published(post_id):
    conn = await get_db()
    try:
        await conn.execute("UPDATE posts SET published=1 WHERE id=?", (post_id,))
        await conn.commit()
    finally:
        await return_db(conn)

async def db_unpublished_count(channel_db_id):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=0", (channel_db_id,))
        row = await cur.fetchone()
        return row[0]
    finally:
        await return_db(conn)

async def db_register_group(chat_id, chat_name, added_by, username=None):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT 1 FROM bot_groups WHERE chat_id=?", (chat_id,))
        if await cur.fetchone() is None:
            added_at = utc_now_iso()
            await conn.execute("INSERT INTO bot_groups (chat_id, chat_name, username, added_by, added_at, banned) VALUES (?,?,?,?,?,0)",
                             (chat_id, chat_name, username, added_by, added_at))
            await conn.execute("INSERT OR IGNORE INTO user_groups_link (user_id, chat_id) VALUES (?,?)", (added_by, chat_id))
            await conn.commit()
            await log_activity("GROUP_ADD", f"{chat_id} → {chat_name} بواسطة {added_by}")
            return True
        else:
            await conn.execute("UPDATE bot_groups SET chat_name=?, username=? WHERE chat_id=?", (chat_name, username, chat_id))
            await conn.execute("INSERT OR IGNORE INTO user_groups_link (user_id, chat_id) VALUES (?,?)", (added_by, chat_id))
            await conn.commit()
            await log_activity("GROUP_UPDATE", f"{chat_id} → {chat_name}")
            return False
    finally:
        await return_db(conn)

async def db_is_group_banned(chat_id):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT banned FROM bot_groups WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        return row[0] == 1 if row else False
    finally:
        await return_db(conn)

async def db_set_group_ban(chat_id, banned):
    conn = await get_db()
    try:
        await conn.execute("UPDATE bot_groups SET banned=? WHERE chat_id=?", (1 if banned else 0, chat_id))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("GROUP_BAN", f"{chat_id} → {'محظورة' if banned else 'غير محظورة'}")

async def db_get_all_groups(only_banned=None):
    conn = await get_db()
    try:
        if only_banned is True:
            cur = await conn.execute("SELECT chat_id, chat_name, username, added_by, added_at, banned FROM bot_groups WHERE banned=1 ORDER BY added_at DESC")
        elif only_banned is False:
            cur = await conn.execute("SELECT chat_id, chat_name, username, added_by, added_at, banned FROM bot_groups WHERE banned=0 ORDER BY added_at DESC")
        else:
            cur = await conn.execute("SELECT chat_id, chat_name, username, added_by, added_at, banned FROM bot_groups ORDER BY added_at DESC")
        return await cur.fetchall()
    finally:
        await return_db(conn)

async def db_get_user_groups_count(user_id):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT COUNT(*) FROM user_groups_link WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0]
    finally:
        await return_db(conn)

async def db_get_user_groups(user_id):
    conn = await get_db()
    try:
        cur = await conn.execute("""
            SELECT bg.chat_id, bg.chat_name, bg.username, bg.banned
            FROM bot_groups bg INNER JOIN user_groups_link ugl ON bg.chat_id = ugl.chat_id
            WHERE ugl.user_id = ? ORDER BY bg.added_at DESC
        """, (user_id,))
        return await cur.fetchall()
    finally:
        await return_db(conn)

async def db_register_channel(channel_id, channel_name, added_by):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT 1 FROM bot_channels WHERE channel_id=?", (channel_id,))
        if await cur.fetchone() is None:
            await conn.execute("INSERT INTO bot_channels (channel_id, channel_name, added_by, added_at, banned) VALUES (?,?,?,?,0)",
                             (channel_id, channel_name, added_by, utc_now_iso()))
        else:
            await conn.execute("UPDATE bot_channels SET channel_name=? WHERE channel_id=?", (channel_name, channel_id))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("BOT_CHANNEL_ADD", f"{channel_id} بواسطة {added_by}")

async def db_is_channel_bot_banned(channel_id):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT banned FROM bot_channels WHERE channel_id=?", (channel_id,))
        row = await cur.fetchone()
        return row[0] == 1 if row else False
    finally:
        await return_db(conn)

async def db_set_channel_bot_ban(channel_id, banned):
    conn = await get_db()
    try:
        await conn.execute("UPDATE bot_channels SET banned=? WHERE channel_id=?", (1 if banned else 0, channel_id))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("BOT_CHANNEL_BAN", f"{channel_id} → {'محظورة' if banned else 'غير محظورة'}")

async def db_get_all_bot_channels(only_banned=None):
    conn = await get_db()
    try:
        if only_banned is True:
            cur = await conn.execute("SELECT channel_id, channel_name, added_by, added_at, banned FROM bot_channels WHERE banned=1 ORDER BY added_at DESC")
        elif only_banned is False:
            cur = await conn.execute("SELECT channel_id, channel_name, added_by, added_at, banned FROM bot_channels WHERE banned=0 ORDER BY added_at DESC")
        else:
            cur = await conn.execute("SELECT channel_id, channel_name, added_by, added_at, banned FROM bot_channels ORDER BY added_at DESC")
        return await cur.fetchall()
    finally:
        await return_db(conn)

async def db_stats():
    conn = await get_db()
    try:
        total = (await (await conn.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        banned = (await (await conn.execute("SELECT COUNT(*) FROM users WHERE banned=1")).fetchone())[0]
        posts = (await (await conn.execute("SELECT COUNT(*) FROM posts WHERE published=0")).fetchone())[0]
        groups = (await (await conn.execute("SELECT COUNT(*) FROM bot_groups")).fetchone())[0]
        channels = (await (await conn.execute("SELECT COUNT(*) FROM user_channels")).fetchone())[0]
        return total, banned, posts, groups, channels
    finally:
        await return_db(conn)

async def db_add_reply(keyword, reply):
    conn = await get_db()
    try:
        await conn.execute("INSERT OR REPLACE INTO group_replies (keyword, reply) VALUES (?,?)", (keyword.lower(), reply))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("REPLY_ADD", f"{keyword} → {reply[:50]}")

async def db_del_reply(keyword):
    conn = await get_db()
    try:
        await conn.execute("DELETE FROM group_replies WHERE keyword=?", (keyword.lower(),))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("REPLY_DELETE", keyword)

async def db_get_reply(keyword):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT reply FROM group_replies WHERE keyword=?", (keyword.lower(),))
        row = await cur.fetchone()
        return row[0] if row else None
    finally:
        await return_db(conn)

async def db_get_all_replies():
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT keyword, reply FROM group_replies ORDER BY keyword")
        return await cur.fetchall()
    finally:
        await return_db(conn)

async def db_get_security_settings(chat_id):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT delete_links, delete_mentions, warn_message, slow_mode, slow_mode_seconds, welcome_enabled, welcome_text, goodbye_enabled, goodbye_text, delete_banned_words FROM group_security WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        if row:
            return {
                'links': row[0] == 1,
                'mentions': row[1] == 1,
                'warn': row[2] == 1,
                'slow_mode': row[3] == 1,
                'slow_mode_seconds': row[4] if row[4] is not None else 5,
                'welcome_enabled': row[5] == 1,
                'welcome_text': row[6] if row[6] else "مرحباً {user} في {chat} 🤍",
                'goodbye_enabled': row[7] == 1,
                'goodbye_text': row[8] if row[8] else "وداعاً {user} 👋",
                'delete_banned_words': row[9] == 1 if len(row) > 9 else False
            }
        else:
            await conn.execute("INSERT INTO group_security (chat_id, delete_links, delete_mentions, warn_message, slow_mode, slow_mode_seconds, welcome_enabled, welcome_text, goodbye_enabled, goodbye_text, delete_banned_words) VALUES (?,0,0,1,0,5,0,'مرحباً {user} في {chat} 🤍',0,'وداعاً {user} 👋',0)", (chat_id,))
            await conn.commit()
            return {
                'links': False,
                'mentions': False,
                'warn': True,
                'slow_mode': False,
                'slow_mode_seconds': 5,
                'welcome_enabled': False,
                'welcome_text': "مرحباً {user} في {chat} 🤍",
                'goodbye_enabled': False,
                'goodbye_text': "وداعاً {user} 👋",
                'delete_banned_words': False
            }
    finally:
        await return_db(conn)

async def db_set_security_settings(chat_id, **kwargs):
    conn = await get_db()
    try:
        curr = await db_get_security_settings(chat_id)
        for k, v in kwargs.items():
            curr[k] = v
        await conn.execute("UPDATE group_security SET delete_links=?, delete_mentions=?, warn_message=?, slow_mode=?, slow_mode_seconds=?, welcome_enabled=?, welcome_text=?, goodbye_enabled=?, goodbye_text=?, delete_banned_words=? WHERE chat_id=?",
                         (1 if curr['links'] else 0, 1 if curr['mentions'] else 0, 1 if curr['warn'] else 0,
                          1 if curr['slow_mode'] else 0, curr['slow_mode_seconds'],
                          1 if curr['welcome_enabled'] else 0, curr['welcome_text'],
                          1 if curr['goodbye_enabled'] else 0, curr['goodbye_text'],
                          1 if curr['delete_banned_words'] else 0, chat_id))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("SECURITY_UPDATE", f"{chat_id}")

async def db_check_slow_mode(chat_id, user_id):
    settings = await db_get_security_settings(chat_id)
    if not settings['slow_mode']:
        return True
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT message_time FROM user_messages WHERE user_id=? AND chat_id=?", (user_id, chat_id))
        row = await cur.fetchone()
        now = utc_now()
        if row:
            last_time = datetime.fromisoformat(row[0])
            last_time = to_naive(last_time)  # تحويل إلى naive
            if (now - last_time).total_seconds() < settings['slow_mode_seconds']:
                return False
        await conn.execute("INSERT OR REPLACE INTO user_messages (user_id, chat_id, message_time) VALUES (?,?,?)", (user_id, chat_id, now.isoformat()))
        await conn.commit()
        return True
    finally:
        await return_db(conn)

async def db_add_banned_word(word: str, chat_id: int, added_by: int):
    conn = await get_db()
    try:
        await conn.execute("INSERT INTO banned_words (word, chat_id, added_by, added_at) VALUES (?,?,?,?)",
                       (word.lower(), chat_id, added_by, utc_now_iso()))
        await conn.commit()
        await log_activity("BANNED_WORD_ADD", f"{word} في {chat_id}")
        return True
    except:
        return False
    finally:
        await return_db(conn)

async def db_remove_banned_word(word: str, chat_id: int):
    conn = await get_db()
    try:
        await conn.execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", (word.lower(), chat_id))
        await conn.commit()
        await log_activity("BANNED_WORD_REMOVE", f"{word} من {chat_id}")
        return True
    finally:
        await return_db(conn)

async def db_get_banned_words(chat_id: int):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT word, added_by, added_at FROM banned_words WHERE chat_id=? ORDER BY word", (chat_id,))
        return await cur.fetchall()
    finally:
        await return_db(conn)

async def db_contains_banned_word(text: str, chat_id: int):
    text_lower = text.lower()
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT word FROM banned_words WHERE chat_id=?", (chat_id,))
        words = await cur.fetchall()
        for (word,) in words:
            if word in text_lower or re.search(rf'\b{re.escape(word)}\b', text_lower):
                return word
        return None
    finally:
        await return_db(conn)

async def db_register_hidden_owner_group(chat_id: int, owner_id: int):
    conn = await get_db()
    try:
        await conn.execute("INSERT OR REPLACE INTO hidden_owner_groups (chat_id, owner_id, is_hidden) VALUES (?,?,1)", (chat_id, owner_id))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("HIDDEN_OWNER_REGISTER", f"{chat_id} بواسطة {owner_id}")

async def db_is_hidden_owner(chat_id: int, user_id: int) -> bool:
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT 1 FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?", (chat_id, user_id))
        return await cur.fetchone() is not None
    finally:
        await return_db(conn)

async def db_get_hidden_owner(chat_id: int):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT owner_id FROM hidden_owner_groups WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        return row[0] if row else None
    finally:
        await return_db(conn)

async def db_get_user_total_posts(user_id):
    conn = await get_db()
    try:
        cur = await conn.execute('''SELECT COUNT(*) FROM posts JOIN user_channels ON posts.channel_db_id = user_channels.id WHERE user_channels.user_id = ?''', (user_id,))
        row = await cur.fetchone()
        return row[0]
    finally:
        await return_db(conn)

async def db_get_user_unpublished_posts(user_id):
    conn = await get_db()
    try:
        cur = await conn.execute('''SELECT COUNT(*) FROM posts JOIN user_channels ON posts.channel_db_id = user_channels.id WHERE user_channels.user_id = ? AND posts.published = 0''', (user_id,))
        row = await cur.fetchone()
        return row[0]
    finally:
        await return_db(conn)

async def db_get_user_channels_count(user_id):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT COUNT(*) FROM user_channels WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0]
    finally:
        await return_db(conn)

async def db_get_user_posts_for_channel(channel_db_id, limit=15):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT id, text, media_type FROM posts WHERE channel_db_id=? AND published=0 ORDER BY id LIMIT ?", (channel_db_id, limit))
        return await cur.fetchall()
    finally:
        await return_db(conn)

async def db_delete_single_post(post_id, user_id, channel_db_id):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT 1 FROM user_channels WHERE id=? AND user_id=?", (channel_db_id, user_id))
        if await cur.fetchone():
            await conn.execute("DELETE FROM posts WHERE id=? AND channel_db_id=?", (post_id, channel_db_id))
            await conn.commit()
            await log_activity("POST_DELETE", f"{post_id} للمستخدم {user_id}")
            return True
        return False
    finally:
        await return_db(conn)

async def db_reset_posts_to_unpublished(channel_db_id, user_id):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT 1 FROM user_channels WHERE id=? AND user_id=?", (channel_db_id, user_id))
        if await cur.fetchone():
            await conn.execute("UPDATE posts SET published=0 WHERE channel_db_id=?", (channel_db_id,))
            await conn.commit()
            await log_activity("POSTS_RECYCLE", f"{channel_db_id} للمستخدم {user_id}")
            return True
        return False
    finally:
        await return_db(conn)

async def db_all_users_channels(only_banned=None):
    conn = await get_db()
    try:
        if only_banned is True:
            cur = await conn.execute('''SELECT u.user_id, uc.id, uc.channel_id, uc.channel_name, uc.banned FROM user_channels uc JOIN users u ON uc.user_id = u.user_id WHERE uc.banned=1 ORDER BY uc.channel_name ASC''')
        elif only_banned is False:
            cur = await conn.execute('''SELECT u.user_id, uc.id, uc.channel_id, uc.channel_name, uc.banned FROM user_channels uc JOIN users u ON uc.user_id = u.user_id WHERE uc.banned=0 ORDER BY uc.channel_name ASC''')
        else:
            cur = await conn.execute('''SELECT u.user_id, uc.id, uc.channel_id, uc.channel_name, uc.banned FROM user_channels uc JOIN users u ON uc.user_id = u.user_id ORDER BY uc.channel_name ASC''')
        return await cur.fetchall()
    finally:
        await return_db(conn)

async def db_get_updates_channel():
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT value FROM settings WHERE key='updates_channel'")
        row = await cur.fetchone()
        return row[0] if row else "zzimmiie"
    finally:
        await return_db(conn)

async def db_set_updates_channel(channel_username):
    clean = channel_username.strip().lstrip('@')
    conn = await get_db()
    try:
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('updates_channel', ?)", (clean,))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("UPDATES_CHANNEL", clean)

async def db_is_bot_admin(user_id):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT 1 FROM bot_admins WHERE user_id=?", (user_id,))
        return await cur.fetchone() is not None
    finally:
        await return_db(conn)

async def db_add_bot_admin(user_id):
    conn = await get_db()
    try:
        await conn.execute("INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)", (user_id,))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("ADMIN_ADD", f"{user_id}")

async def db_remove_bot_admin(user_id):
    conn = await get_db()
    try:
        await conn.execute("DELETE FROM bot_admins WHERE user_id=?", (user_id,))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("ADMIN_REMOVE", f"{user_id}")

async def db_get_all_users():
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT user_id, banned FROM users ORDER BY user_id")
        return await cur.fetchall()
    finally:
        await return_db(conn)

async def db_has_used_trial(user_id):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT trial_used FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] == 1 if row else False
    finally:
        await return_db(conn)

async def db_activate_trial(user_id):
    if await db_has_active_subscription(user_id):
        return 0
    end_date = (utc_now() + timedelta(days=30)).isoformat()
    conn = await get_db()
    try:
        await conn.execute("UPDATE users SET trial_used=1, subscription_end=? WHERE user_id=?", (end_date, user_id))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("TRIAL_ACTIVATE", f"{user_id}")
    return 30

async def db_has_active_subscription(user_id):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT subscription_end FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if not row or not row[0]:
            return False
        try:
            end_date = datetime.fromisoformat(row[0])
            end_date = to_naive(end_date)
            return end_date > utc_now()
        except:
            return False
    finally:
        await return_db(conn)

async def db_activate_subscription(user_id, days=30):
    end_date = (utc_now() + timedelta(days=days)).isoformat()
    conn = await get_db()
    try:
        await conn.execute("UPDATE users SET subscription_end=? WHERE user_id=?", (end_date, user_id))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("SUBSCRIPTION_ACTIVATE", f"{user_id} → {days} يوم")
    return days

async def db_get_subscription_days_left(user_id):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT subscription_end FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if not row or not row[0]:
            return 0
        try:
            end_date = datetime.fromisoformat(row[0])
            end_date = to_naive(end_date)
            delta = end_date - utc_now()
            return max(0, delta.days)
        except:
            return 0
    finally:
        await return_db(conn)

async def db_get_force_subscribe_status():
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT value FROM settings WHERE key='force_subscribe_enabled'")
        row = await cur.fetchone()
        return row[0] == '1' if row else False
    finally:
        await return_db(conn)

async def db_set_force_subscribe_status(enabled):
    conn = await get_db()
    try:
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('force_subscribe_enabled', ?)", ('1' if enabled else '0',))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("FORCE_SUBSCRIBE", "مفعل" if enabled else "معطل")

async def db_get_force_subscribe_channel():
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT value FROM settings WHERE key='force_subscribe_channel'")
        row = await cur.fetchone()
        return row[0] if row else ""
    finally:
        await return_db(conn)

async def db_set_force_subscribe_channel(channel):
    clean = channel.strip().lstrip('@')
    conn = await get_db()
    try:
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('force_subscribe_channel', ?)", (clean,))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("FORCE_SUBSCRIBE_CHANNEL", clean)

async def db_get_active_channel(user_id):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT value FROM settings WHERE key=?", (f"active_channel_{user_id}",))
        row = await cur.fetchone()
        return safe_int_convert(row[0]) if row and row[0] else None
    finally:
        await return_db(conn)

async def db_set_active_channel(user_id, channel_db_id):
    conn = await get_db()
    try:
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (f"active_channel_{user_id}", str(channel_db_id)))
        await conn.commit()
    finally:
        await return_db(conn)

# ==================== دوال الجدولة ====================
async def db_add_scheduled_post(chat_id: int, text: str, publish_time: datetime):
    conn = await get_db()
    try:
        await conn.execute(
            "INSERT INTO scheduled_posts (chat_id, text, publish_time) VALUES (?, ?, ?)",
            (chat_id, text, publish_time.isoformat())
        )
        await conn.commit()
    finally:
        await return_db(conn)

async def db_get_due_scheduled_posts(now: datetime):
    conn = await get_db()
    try:
        cur = await conn.execute(
            "SELECT id, chat_id, text, fail_count FROM scheduled_posts WHERE publish_time <= ?",
            (now.isoformat(),)
        )
        return await cur.fetchall()
    finally:
        await return_db(conn)

async def db_update_scheduled_post_fail(post_id: int, fail_count: int):
    conn = await get_db()
    try:
        await conn.execute("UPDATE scheduled_posts SET fail_count = ? WHERE id = ?", (fail_count, post_id))
        await conn.commit()
    finally:
        await return_db(conn)

async def db_delete_scheduled_post(post_id: int):
    conn = await get_db()
    try:
        await conn.execute("DELETE FROM scheduled_posts WHERE id = ?", (post_id,))
        await conn.commit()
    finally:
        await return_db(conn)

async def db_save_schedule(channel_db_id: int, schedule_type: str, interval_minutes: int = None, interval_hours: int = None, interval_days: int = None, days_of_week: str = None, specific_dates: str = None, publish_time: str = None):
    if not await db_channel_exists(channel_db_id):
        return False

    if schedule_type == 'interval_minutes' and interval_minutes is not None and interval_minutes < 1:
        interval_minutes = 1
    if schedule_type == 'interval_hours' and interval_hours is not None and interval_hours < 1:
        interval_hours = 1
    if schedule_type == 'interval_days' and interval_days is not None and interval_days < 1:
        interval_days = 1

    conn = await get_db()
    try:
        cur = await conn.execute("SELECT publish_time FROM schedule WHERE channel_db_id=?", (channel_db_id,))
        row = await cur.fetchone()
        current_time = publish_time if publish_time is not None else (row[0] if row else "00:00")
        next_date = (utc_now() + timedelta(minutes=1)).isoformat()

        if schedule_type == 'interval_minutes':
            interval = interval_minutes if interval_minutes is not None else 12
            await conn.execute("INSERT OR REPLACE INTO schedule (channel_db_id, schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time, next_publish_date) VALUES (?, 'interval_minutes', ?, 0, 0, '', '', ?, ?)", (channel_db_id, interval, current_time, next_date))
        elif schedule_type == 'interval_hours':
            hours = interval_hours if interval_hours is not None else 1
            await conn.execute("INSERT OR REPLACE INTO schedule (channel_db_id, schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time, next_publish_date) VALUES (?, 'interval_hours', 0, ?, 0, '', '', ?, ?)", (channel_db_id, hours, current_time, next_date))
        elif schedule_type == 'interval_days':
            days = interval_days if interval_days is not None else 1
            await conn.execute("INSERT OR REPLACE INTO schedule (channel_db_id, schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time, next_publish_date) VALUES (?, 'interval_days', 0, 0, ?, '', '', ?, ?)", (channel_db_id, days, current_time, next_date))
        elif schedule_type == 'days':
            days = days_of_week if days_of_week is not None else ''
            await conn.execute("INSERT OR REPLACE INTO schedule (channel_db_id, schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time, next_publish_date) VALUES (?, 'days', 0, 0, 0, ?, '', ?, ?)", (channel_db_id, days, current_time, next_date))
        elif schedule_type == 'dates':
            dates = specific_dates if specific_dates is not None else ''
            await conn.execute("INSERT OR REPLACE INTO schedule (channel_db_id, schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time, next_publish_date) VALUES (?, 'dates', 0, 0, 0, '', ?, ?, ?)", (channel_db_id, dates, current_time, next_date))

        await conn.commit()
        return True
    finally:
        await return_db(conn)
    await log_activity("SCHEDULE_UPDATE", f"{channel_db_id} → {schedule_type}")

async def db_get_schedule(channel_db_id: int):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time, next_publish_date FROM schedule WHERE channel_db_id=?", (channel_db_id,))
        row = await cur.fetchone()
        if row:
            return {
                'type': row[0],
                'interval_minutes': row[1],
                'interval_hours': row[2],
                'interval_days': row[3],
                'days_of_week': row[4],
                'specific_dates': row[5],
                'publish_time': row[6] or '00:00',
                'next_publish_date': row[7]
            }
        next_date = (utc_now() + timedelta(minutes=1)).isoformat()
        await conn.execute("INSERT OR REPLACE INTO schedule (channel_db_id, schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time, next_publish_date) VALUES (?, 'interval_minutes', 12, 0, 0, '', '', '00:00', ?)",
                         (channel_db_id, next_date))
        await conn.commit()
        return {
            'type': 'interval_minutes',
            'interval_minutes': 12,
            'interval_hours': 0,
            'interval_days': 0,
            'days_of_week': '',
            'specific_dates': '',
            'publish_time': '00:00',
            'next_publish_date': next_date
        }
    finally:
        await return_db(conn)

async def db_set_publish_time(channel_db_id: int, time_str: str):
    conn = await get_db()
    try:
        await conn.execute("UPDATE schedule SET publish_time=? WHERE channel_db_id=?", (time_str, channel_db_id))
        next_date = (utc_now() + timedelta(minutes=1)).isoformat()
        await conn.execute("UPDATE schedule SET next_publish_date = ? WHERE channel_db_id = ?", (next_date, channel_db_id))
        await conn.commit()
    finally:
        await return_db(conn)

async def db_set_next_publish_date(channel_db_id: int, next_date: str):
    conn = await get_db()
    try:
        await conn.execute("UPDATE schedule SET next_publish_date=? WHERE channel_db_id=?", (next_date, channel_db_id))
        await conn.commit()
    finally:
        await return_db(conn)

async def db_get_last_publish(channel_db_id: int):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT last_publish_time FROM last_publish WHERE channel_db_id=?", (channel_db_id,))
        row = await cur.fetchone()
        if row and row[0]:
            dt = datetime.fromisoformat(row[0])
            dt = to_naive(dt)
            return dt
        return None
    finally:
        await return_db(conn)

async def db_set_last_publish(channel_db_id: int, time: datetime):
    conn = await get_db()
    try:
        await conn.execute("INSERT OR REPLACE INTO last_publish (channel_db_id, last_publish_time) VALUES (?,?)",
                         (channel_db_id, time.isoformat()))
        await conn.commit()
    finally:
        await return_db(conn)

async def db_calculate_next_publish_date(channel_db_id: int) -> str:
    schedule = await db_get_schedule(channel_db_id)
    publish_time = parse_time_safe(schedule.get('publish_time', '00:00'))
    if not publish_time:
        publish_time = (0, 0)
    hour, minute = publish_time
    now_utc = utc_now()

    if schedule['type'] == 'interval_minutes':
        interval_sec = (schedule['interval_minutes'] or 12) * 60
        next_date = now_utc + timedelta(seconds=interval_sec)
        return next_date.isoformat()
    elif schedule['type'] == 'interval_hours':
        interval_sec = (schedule['interval_hours'] or 1) * 3600
        next_date = now_utc + timedelta(seconds=interval_sec)
        return next_date.isoformat()
    elif schedule['type'] == 'interval_days':
        interval_sec = (schedule['interval_days'] or 1) * 86400
        next_date = now_utc + timedelta(seconds=interval_sec)
        return next_date.isoformat()
    elif schedule['type'] == 'days':
        if not schedule['days_of_week']:
            return None
        days = parse_days_of_week_safe(schedule['days_of_week'])
        if not days:
            return None
        utc_hour = hour - 3
        if utc_hour < 0:
            utc_hour += 24
        for i in range(1, 8):
            next_day = now_utc + timedelta(days=i)
            if next_day.weekday() in days:
                result = next_day.replace(hour=utc_hour, minute=minute, second=0, microsecond=0)
                if result <= now_utc:
                    result += timedelta(days=7)
                return result.isoformat()
        return None
    elif schedule['type'] == 'dates':
        if not schedule['specific_dates']:
            return None
        dates = parse_dates_safe(schedule['specific_dates'])
        if not dates:
            return None
        now_mecca = mecca_now()
        today_mecca = now_mecca.date()
        utc_hour = hour - 3
        if utc_hour < 0:
            utc_hour += 24
        for date_str in sorted(dates):
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                if date_obj >= today_mecca:
                    result = datetime.combine(date_obj, datetime.min.time()).replace(hour=utc_hour, minute=minute)
                    if result <= now_utc:
                        result += timedelta(days=1)
                    return result.isoformat()
            except:
                continue
        return None
    return None

async def db_update_next_publish_date(channel_db_id: int):
    last_publish = await db_get_last_publish(channel_db_id)
    if last_publish:
        schedule = await db_get_schedule(channel_db_id)
        if schedule['type'] == 'interval_minutes':
            interval_sec = (schedule['interval_minutes'] or 12) * 60
            next_date = last_publish + timedelta(seconds=interval_sec)
            await db_set_next_publish_date(channel_db_id, next_date.isoformat())
        elif schedule['type'] == 'interval_hours':
            interval_sec = (schedule['interval_hours'] or 1) * 3600
            next_date = last_publish + timedelta(seconds=interval_sec)
            await db_set_next_publish_date(channel_db_id, next_date.isoformat())
        elif schedule['type'] == 'interval_days':
            interval_sec = (schedule['interval_days'] or 1) * 86400
            next_date = last_publish + timedelta(seconds=interval_sec)
            await db_set_next_publish_date(channel_db_id, next_date.isoformat())
        else:
            new_next = await db_calculate_next_publish_date(channel_db_id)
            if new_next:
                await db_set_next_publish_date(channel_db_id, new_next)
    else:
        next_date = (utc_now() + timedelta(minutes=1)).isoformat()
        await db_set_next_publish_date(channel_db_id, next_date)

async def db_get_publish_interval():
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT value FROM settings WHERE key='publish_interval'")
        row = await cur.fetchone()
        return int(row[0]) if row else 12 * 60
    finally:
        await return_db(conn)

async def db_set_publish_interval_seconds(seconds, user_id=None, is_admin=False):
    minutes = seconds // 60
    min_allowed = 10 if is_admin or user_id == MAIN_ADMIN_ID or await db_is_bot_admin(user_id) else 12
    if minutes < min_allowed:
        minutes = min_allowed
        seconds = minutes * 60
    conn = await get_db()
    try:
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('publish_interval', ?)", (str(seconds),))
        await conn.commit()
    finally:
        await return_db(conn)
    await log_activity("INTERVAL_CHANGE", f"{minutes} دقيقة بواسطة {user_id}")

# ==================== دوال القفل ====================
async def db_set_chat_lock(chat_id: int, locked: bool, locked_by: int = None):
    conn = await get_db()
    try:
        if locked:
            locked_at = utc_now_iso()
            await conn.execute("INSERT OR REPLACE INTO chat_locks (chat_id, locked, locked_at, locked_by) VALUES (?, ?, ?, ?)",
                             (chat_id, 1, locked_at, locked_by))
        else:
            await conn.execute("DELETE FROM chat_locks WHERE chat_id=?", (chat_id,))
        await conn.commit()
    finally:
        await return_db(conn)

async def db_get_chat_lock(chat_id: int) -> bool:
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT locked FROM chat_locks WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        return row[0] == 1 if row else False
    finally:
        await return_db(conn)

# ==================== دوال الدعم ====================
async def db_get_next_ticket_number():
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT value FROM settings WHERE key='last_ticket_number'")
        row = await cur.fetchone()
        last_num = int(row[0]) if row else 0
        new_num = last_num + 1
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('last_ticket_number', ?)", (str(new_num),))
        await conn.commit()
        return new_num
    finally:
        await return_db(conn)

async def db_save_ticket(user_id, username, message, ticket_num):
    conn = await get_db()
    try:
        created_at = utc_now_iso()
        await conn.execute("INSERT INTO support_tickets (user_id, username, message, ticket_number, status, created_at) VALUES (?,?,?,?,?,?)",
                        (user_id, username, message, ticket_num, 'pending', created_at))
        await conn.commit()
        return True
    finally:
        await return_db(conn)

async def db_get_user_ticket(user_id):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT ticket_number, status, created_at FROM support_tickets WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
        return await cur.fetchone()
    finally:
        await return_db(conn)

async def db_get_all_tickets(limit=20):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT id, user_id, username, message, ticket_number, status, created_at FROM support_tickets ORDER BY id DESC LIMIT ?", (limit,))
        return await cur.fetchall()
    finally:
        await return_db(conn)

async def db_get_last_ticket_id_for_user(user_id):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT id FROM support_tickets WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else None
    finally:
        await return_db(conn)

async def db_mark_ticket_replied(ticket_id):
    conn = await get_db()
    try:
        await conn.execute("UPDATE support_tickets SET status='replied', replied=1 WHERE id=?", (ticket_id,))
        await conn.commit()
    finally:
        await return_db(conn)

# ==================== دوال صلاحية /sendcode ====================
async def db_get_allowed_sendcode_user() -> int | None:
    """الحصول على user_id المسموح له باستخدام /sendcode"""
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT user_id FROM allowed_sendcode_user WHERE id=1")
        row = await cur.fetchone()
        return row[0] if row else None
    finally:
        await return_db(conn)

async def db_set_allowed_sendcode_user(user_id: int) -> None:
    """تعيين user_id المسموح له باستخدام /sendcode"""
    conn = await get_db()
    try:
        await conn.execute("INSERT OR REPLACE INTO allowed_sendcode_user (id, user_id) VALUES (1, ?)", (user_id,))
        await conn.commit()
    finally:
        await return_db(conn)

# ==================== دوال الأمان والمشرفين ====================
async def get_cached_admins(bot, chat_id: int) -> list:
    now = time_module.time()
    if chat_id in _admins_cache:
        cached_data, timestamp = _admins_cache[chat_id]
        if now - timestamp < _ADMINS_CACHE_TTL:
            return cached_data
    try:
        admins = await bot.get_chat_administrators(chat_id)
        _admins_cache[chat_id] = (admins, now)
        return admins
    except Exception as e:
        logger.error(f"خطأ في جلب المشرفين: {e}")
        return _admins_cache.get(chat_id, (None, 0))[0] if chat_id in _admins_cache else []

async def invalidate_admins_cache(chat_id: int):
    if chat_id in _admins_cache:
        del _admins_cache[chat_id]

async def is_group_admin(bot, chat_id: int, user_id: int) -> bool:
    if await db_is_hidden_owner(chat_id, user_id):
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except:
        return False

# ==================== دوال النسخ الاحتياطي ====================
async def create_backup():
    backup_file = BACKUP_DIR / f"backup_{mecca_now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(DB_PATH, backup_file)
    backups = sorted(BACKUP_DIR.glob("backup_*.db"), key=lambda x: x.stat().st_mtime, reverse=True)
    for old_backup in backups[10:]:
        old_backup.unlink()
    logger.info(f"✅ تم إنشاء نسخة احتياطية: {backup_file}")
    await log_activity("BACKUP_CREATED", str(backup_file))
    return backup_file

async def list_backups():
    return sorted(BACKUP_DIR.glob("backup_*.db"), key=lambda x: x.stat().st_mtime, reverse=True)

async def restore_backup(backup_path: Path):
    if not backup_path.exists():
        raise FileNotFoundError(f"الملف {backup_path} غير موجود")
    shutil.copy2(backup_path, DB_PATH)
    await db_pool.initialize()
    logger.info(f"✅ تم استعادة النسخة الاحتياطية: {backup_path}")
    await log_activity("BACKUP_RESTORED", str(backup_path))

async def auto_backup():
    while True:
        await asyncio.sleep(24 * 60 * 60)
        try:
            conn = await get_db()
            try:
                cur = await conn.execute("SELECT value FROM settings WHERE key='auto_backup'")
                row = await cur.fetchone()
                if row and row[0] == '1':
                    await create_backup()
                    await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('last_backup', ?)", (utc_now_iso(),))
                    await conn.commit()
            finally:
                await return_db(conn)
        except Exception as e:
            logger.error(f"⚠️ خطأ في النسخ الاحتياطي التلقائي: {e}")

# ==================== دوال الاشتراك الإجباري ====================
async def is_user_subscribed(bot, user_id, channel):
    if not channel:
        return True
    channel = channel.lstrip('@')
    try:
        member = await bot.get_chat_member(f"@{channel}", user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

async def ensure_force_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None) -> bool:
    if user_id is None:
        if update.effective_user is None:
            return True
        user_id = update.effective_user.id
    if user_id == MAIN_ADMIN_ID or await db_is_bot_admin(user_id):
        return True
    if not await db_get_force_subscribe_status():
        return True
    channel = await db_get_force_subscribe_channel()
    if not channel:
        return True
    if await is_user_subscribed(context.bot, user_id, channel):
        return True
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 اشترك في القناة", url=f"https://t.me/{channel.lstrip('@')}"),
         InlineKeyboardButton("🔄 تأكد من الاشتراك", callback_data="check_subscribe")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="main")]
    ])
    msg = f"🔒 **اشتراك إجباري**\n\nيجب عليك الاشتراك في قناتنا أولاً:\n👉 @{channel.lstrip('@')}\n\nبعد الاشتراك، اضغط على زر التحقق."
    try:
        if update.callback_query:
            if update.callback_query.message.text == msg:
                return False
            await update.callback_query.edit_message_text(msg, reply_markup=keyboard, parse_mode="Markdown")
        elif update.message:
            await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="Markdown")
    except Exception:
        pass
    return False

# ==================== دوال المستويات ====================
LEVEL_REQUIREMENTS = {
    1: 0, 2: 100, 3: 250, 4: 500, 5: 1000,
    6: 2000, 7: 3500, 8: 5000, 9: 7500, 10: 10000
}

user_points_last_hour = defaultdict(lambda: (0, 0))

async def db_get_user_level(user_id: int):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT points, level FROM user_levels WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row:
            return {'points': row[0], 'level': row[1]}
        return {'points': 0, 'level': 1}
    finally:
        await return_db(conn)

async def db_update_user_level(user_id: int, points: int, level: int):
    conn = await get_db()
    try:
        await conn.execute("INSERT OR REPLACE INTO user_levels (user_id, points, level) VALUES (?,?,?)", (user_id, points, level))
        await conn.commit()
    finally:
        await return_db(conn)

async def add_points(user_id: int, update: Update = None, context: ContextTypes.DEFAULT_TYPE = None):
    now = utc_now()
    count, last_hour = user_points_last_hour.get(user_id, (0, 0))
    if last_hour:
        last_time = datetime.utcfromtimestamp(last_hour)  # استخدام utcfromtimestamp بدلاً من fromtimestamp
        if (now - last_time).total_seconds() < 3600:
            if count >= 20:
                return
            new_count = count + 1
        else:
            new_count = 1
    else:
        new_count = 1
    user_points_last_hour[user_id] = (new_count, now.timestamp())

    data = await db_get_user_level(user_id)
    old_level = data['level']
    points = data['points'] + 1
    level = old_level

    new_levels = []
    for lvl, pts in LEVEL_REQUIREMENTS.items():
        if points >= pts and lvl > level:
            new_levels.append(lvl)
            level = lvl

    if new_levels and update and update.effective_user:
        try:
            if len(new_levels) == 1:
                msg = f"🎉 **تهانينا!**\nلقد وصلت إلى المستوى {new_levels[0]}! 🎉"
            else:
                msg = f"🎉 **تهانينا!**\nلقد تقدمت {len(new_levels)} مستويات إلى المستوى {new_levels[-1]}! 🎉"
            await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")
        except:
            pass

    await db_update_user_level(user_id, points, level)

async def get_rank(user_id: int) -> dict:
    return await db_get_user_level(user_id)

async def get_top_users(limit: int = 10):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT user_id, points, level FROM user_levels ORDER BY points DESC LIMIT ?", (limit,))
        return await cur.fetchall()
    finally:
        await return_db(conn)

# ==================== مكافحة الإغراق ====================
user_messages_times = defaultdict(lambda: deque(maxlen=5))
channel_failure_count = defaultdict(int)
chat_locks = {}

async def check_anti_flood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_user is None or update.effective_chat is None:
        return True
    if update.effective_user.is_bot:
        return True

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if await is_group_admin(context.bot, chat_id, user_id):
        return True

    now = utc_now()
    times = user_messages_times[user_id]
    while times and (now - times[0]).total_seconds() < 10:
        times.popleft()
    if len(times) >= 5:
        try:
            await update.message.delete()
            warning = await update.message.reply_text("⚠️ **تحذير: تجاوزت حد الإرسال!**\nيرجى الانتظار 10 ثواني.", parse_mode="Markdown")
            await asyncio.sleep(5)
            await warning.delete()
        except:
            pass
        return False
    times.append(now)
    return True

async def is_chat_locked(chat_id: int) -> bool:
    return await db_get_chat_lock(chat_id)

async def lock_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat is None or update.effective_user is None:
        return
    if update.effective_chat.type == 'private':
        await update.message.reply_text(get_text(update.effective_user.id, 'group_only'))
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not await is_group_admin(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return

    await db_set_chat_lock(chat_id, True, user_id)
    await update.message.reply_text(get_text(user_id, 'locked'), parse_mode="Markdown")

async def unlock_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat is None or update.effective_user is None:
        return
    if update.effective_chat.type == 'private':
        await update.message.reply_text(get_text(update.effective_user.id, 'group_only'))
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not await is_group_admin(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return

    await db_set_chat_lock(chat_id, False)
    await update.message.reply_text(get_text(user_id, 'unlocked'), parse_mode="Markdown")

async def check_chat_lock_before_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_user is None or update.effective_chat is None:
        return True
    if update.effective_user.is_bot:
        return True

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if await is_chat_locked(chat_id):
        if await is_group_admin(context.bot, chat_id, user_id):
            return True
        try:
            await update.message.delete()
        except:
            pass
        return False
    return True

# ==================== دوال الرسائل والردود ====================
FUNNY_RESPONSES = ["😂😂😂", "😆😆😆", "🤣🤣🤣", "😭😭😭", "🙃🙃🙃", "🥲🥲🥲", "😎😎😎", "🔥🔥🔥"]

async def maybe_send_funny_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    if random.random() < 0.05:
        await update.message.reply_text(random.choice(FUNNY_RESPONSES))

async def handle_shortcuts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.message is None or update.message.text is None:
        return False
    text = update.message.text.strip()
    shortcuts = {
        "!قفل": lock_chat_command,
        "!فتح": unlock_chat_command,
        "!رتبتي": show_rank_command,
        "!توب": show_top_command,
    }
    if text in shortcuts:
        await shortcuts[text](update, context)
        return True
    return False

SMART_RESPONSES = {
    "مرحباً": ["أهلاً وسهلاً بك في مجموعتنا 🤍", "هلا وغلا بك يا غالي 🌹", "مرحباً مليون 🤍"],
    "السلام عليكم": ["وعليكم السلام ورحمة الله وبركاته", "الله يبارك فيك 🌹"],
    "شكراً": ["العفو، تحت أمرك يا غالي 🙏", "الشكر لله 🤍"],
    "كيف حالك": ["الحمدلله بخير، تسلم والله 🌹", "بخير، شكراً لسؤالك 🤍"],
}

async def db_update_random_reply(keyword):
    conn = await get_db()
    try:
        cur = await conn.execute("SELECT reply FROM group_replies WHERE keyword=?", (keyword.lower(),))
        row = await cur.fetchone()
        if not row:
            return
        current_reply = row[0]
        original_replies = SMART_RESPONSES.get(keyword.lower(), [])
        if current_reply in original_replies:
            new_reply = random.choice(original_replies)
            await conn.execute("UPDATE group_replies SET reply=? WHERE keyword=?", (new_reply, keyword.lower()))
            await conn.commit()
    finally:
        await return_db(conn)

# ==================== القائمة الرئيسية ولوحات المفاتيح ====================
def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 المستخدمين", callback_data="admin_users"), InlineKeyboardButton("🚫 محظورين", callback_data="admin_banned_users")],
        [InlineKeyboardButton("📡 قنوات المستخدمين", callback_data="admin_all_channels"), InlineKeyboardButton("⛔ قنوات محظورة", callback_data="admin_banned_channels")],
        [InlineKeyboardButton("📊 المجموعات", callback_data="admin_groups"), InlineKeyboardButton("🚷 مجموعات محظورة", callback_data="admin_banned_groups")],
        [InlineKeyboardButton("📢 قنوات البوت", callback_data="admin_bot_channels"), InlineKeyboardButton("🚫 قنوات بوت محظورة", callback_data="admin_banned_bot_channels")],
        [InlineKeyboardButton("❤️ تنشيط الكل", callback_data="activate_all_channels")],
        [InlineKeyboardButton("📂 مراقبة المستخدمين", callback_data="admin_monitor_users")],
        [InlineKeyboardButton("👑 + مشرف", callback_data="admin_add_admin"), InlineKeyboardButton("🗑️ - مشرف", callback_data="admin_remove_admin")],
        [InlineKeyboardButton("💬 ردود المجموعة", callback_data="admin_replies")],
        [InlineKeyboardButton("🚫 كلمات محظورة (عامة)", callback_data="admin_banned_words")],
        [InlineKeyboardButton("🖥️ حالة الرام", callback_data="admin_ram"), InlineKeyboardButton("📊 إحصائيات عامة", callback_data="admin_stats")],
        [InlineKeyboardButton("💾 نسخة احتياطية", callback_data="admin_backup"), InlineKeyboardButton("🔄 استعادة نسخة", callback_data="admin_restore_backup")],
        [InlineKeyboardButton("⏱️ وقت النشر (عام)", callback_data="admin_change_interval")],
        [InlineKeyboardButton("📢 نشر تحديث", callback_data="admin_send_update"), InlineKeyboardButton("⚙️ قناة التحديثات", callback_data="admin_set_update_channel")],
        [InlineKeyboardButton("🔄 التحديثات", callback_data="admin_updates"), InlineKeyboardButton("⚙️ إعدادات النسخ", callback_data="admin_backup_settings")],
        [InlineKeyboardButton("🔒 الاشتراك الإجباري", callback_data="admin_force_subscribe"), InlineKeyboardButton("⚙️ تعيين القناة", callback_data="admin_set_force_channel")],
        [InlineKeyboardButton("📨 إرسال رسالة", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📋 تذاكر الدعم", callback_data="admin_support_tickets")],
        [InlineKeyboardButton("🗑️ حذف جميع التذاكر", callback_data="admin_delete_all_tickets")],
        [InlineKeyboardButton("📁 صلاحية /sendcode", callback_data="admin_manage_sendcode")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
    ])

def replies_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة رد", callback_data="admin_add_reply"), InlineKeyboardButton("📋 عرض الردود", callback_data="admin_list_replies")],
        [InlineKeyboardButton("🗑️ حذف رد", callback_data="admin_del_reply"), InlineKeyboardButton("🔙 رجوع", callback_data="admin")]
    ])

def security_keyboard(chat_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 حذف الروابط", callback_data=f"sec_links_{chat_id}"), InlineKeyboardButton("@ حذف المعرفات", callback_data=f"sec_mentions_{chat_id}")],
        [InlineKeyboardButton("🔊 رسالة تحذير", callback_data=f"sec_warn_{chat_id}"), InlineKeyboardButton("🚦 الوضع البطيء", callback_data=f"sec_slowmode_{chat_id}")],
        [InlineKeyboardButton("🚫 كلمات محظورة", callback_data=f"sec_banned_words_menu_{chat_id}"), InlineKeyboardButton("🎯 الترحيب", callback_data=f"sec_welcome_{chat_id}")],
        [InlineKeyboardButton("👋 الوداع", callback_data=f"sec_goodbye_{chat_id}"), InlineKeyboardButton("🔙 إغلاق", callback_data="sec_close")]
    ])

def group_banned_words_keyboard(chat_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة كلمة", callback_data=f"group_add_banned_word_{chat_id}"), InlineKeyboardButton("📋 عرض الكلمات", callback_data=f"group_list_banned_words_{chat_id}")],
        [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=f"group_remove_banned_word_{chat_id}"), InlineKeyboardButton("🔙 رجوع", callback_data=f"group_settings_{chat_id}")]
    ])

async def build_days_keyboard(uid, context):
    selected = context.user_data.get('selected_days', [])
    day_names = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    kb_buttons = []
    for i in range(0, 7, 3):
        row = []
        for j in range(3):
            if i + j < 7:
                name = day_names[i + j]
                mark = "✅ " if (i + j) in selected else ""
                row.append(InlineKeyboardButton(f"{mark}{name}", callback_data=f"day_{i + j}"))
        kb_buttons.append(row)
    kb_buttons.append([
        InlineKeyboardButton("✔️ حفظ", callback_data="save_days"),
        InlineKeyboardButton(get_text(uid, 'back'), callback_data="schedule_settings")
    ])
    return InlineKeyboardMarkup(kb_buttons)

async def get_main_keyboard(uid, active_channel_id=None):
    if await db_is_banned(uid):
        return None, "🚫 محظور", None
    channels = await db_get_channels(uid)
    if not channels:
        return None, get_text(uid, 'no_channels'), None
    if active_channel_id is None:
        active_channel_id = channels[0][0]
    cnt = await db_unpublished_count(active_channel_id)
    auto = "🟢" if await db_auto_status(uid) else "🔴"
    ch_info = await db_get_channel_info(active_channel_id)
    if not ch_info:
        return None, get_text(uid, 'channel_error'), None
    ch_id, ch_name, banned = ch_info
    ch_display = f"{ch_name} ({ch_id})" if ch_name != ch_id else ch_id
    if banned:
        ch_display = "⛔ " + ch_display
    my_groups = await db_get_user_groups_count(uid)
    subscribed = await db_has_active_subscription(uid) or await db_has_used_trial(uid)
    subscribed_text = get_text(uid, 'subscribed') if subscribed else get_text(uid, 'not_subscribed')
    auto_text = get_text(uid, 'auto_on') if await db_auto_status(uid) else get_text(uid, 'auto_off')

    kb = [
        [InlineKeyboardButton(get_text(uid, 'add_channel'), callback_data="add_channel"), InlineKeyboardButton(get_text(uid, 'my_channels'), callback_data="list_channels")],
        [InlineKeyboardButton(get_text(uid, 'add_15_posts'), callback_data="new_post_15"), InlineKeyboardButton(get_text(uid, 'publish_one'), callback_data="publish_one")],
        [InlineKeyboardButton(get_text(uid, 'my_posts_btn'), callback_data="my_posts"), InlineKeyboardButton(get_text(uid, 'recycle'), callback_data="recycle_posts")],
        [InlineKeyboardButton(get_text(uid, 'my_stats_btn'), callback_data="my_stats"), InlineKeyboardButton(get_text(uid, 'my_groups_btn'), callback_data="my_groups")],
        [InlineKeyboardButton(f"{get_text(uid, 'stats_btn')} ({cnt})", callback_data="stats"), InlineKeyboardButton(get_text(uid, 'settings_btn'), callback_data="settings")],
        [InlineKeyboardButton(get_text(uid, 'schedule_btn'), callback_data="schedule_settings"), InlineKeyboardButton(get_text(uid, 'security_btn'), callback_data="security_main")],
        [InlineKeyboardButton(get_text(uid, 'my_rank_btn'), callback_data="show_rank"), InlineKeyboardButton(get_text(uid, 'top_10_btn'), callback_data="show_top")],
        [InlineKeyboardButton(get_text(uid, 'schedule_post_btn'), callback_data="schedule_post_ui")],
        [InlineKeyboardButton(get_text(uid, 'help_btn'), callback_data="help"), InlineKeyboardButton(get_text(uid, 'trial_btn'), callback_data="trial")],
        [InlineKeyboardButton(get_text(uid, 'subscribe_btn'), callback_data="subscribe"), InlineKeyboardButton(get_text(uid, 'developer_btn'), callback_data="developer")],
        [InlineKeyboardButton(get_text(uid, 'language_btn'), callback_data="language"), InlineKeyboardButton(get_text(uid, 'support_btn'), callback_data="support")],
        [InlineKeyboardButton(get_text(uid, 'add_to_group'), url=f"https://t.me/{BOT_USERNAME}?startgroup")]
    ]
    if uid == MAIN_ADMIN_ID or await db_is_bot_admin(uid):
        kb.append([InlineKeyboardButton(get_text(uid, 'admin_panel'), callback_data="admin")])

    title = get_text(uid, 'main_title').format(BOT_NAME, uid, my_groups, subscribed_text, ch_display, cnt, auto_text)
    return InlineKeyboardMarkup(kb), title, active_channel_id

# ==================== أوامر البوت الأساسية ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    chat = update.effective_chat
    if chat.type in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ استخدم هذا الأمر في الخاص")
        return
    uid = update.effective_user.id
    user = update.effective_user
    await db_update_user_cache(uid, user.username, user.first_name)

    if not await ensure_force_subscribe(update, context, uid):
        return

    if uid not in user_language:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("العربية 🇸🇦", callback_data="lang_ar"), InlineKeyboardButton("English 🇬🇧", callback_data="lang_en")],
            [InlineKeyboardButton("Français 🇫🇷", callback_data="lang_fr"), InlineKeyboardButton("Türkçe 🇹🇷", callback_data="lang_tr")],
            [InlineKeyboardButton("中文 🇨🇳", callback_data="lang_zh"), InlineKeyboardButton("Русский 🇷🇺", callback_data="lang_ru")]
        ])
        await update.message.reply_text("🌐 اختر لغتك / Choose your language:", reply_markup=keyboard)
        return

    await db_register_user(uid)
    if await db_is_banned(uid):
        await update.message.reply_text("🚫 أنت محظور.")
        return
    active = context.user_data.get('active_channel')
    if not active:
        active = await db_get_active_channel(uid)
    kb, txt, new_active = await get_main_keyboard(uid, active)
    if kb is None:
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'add_channel'), callback_data="add_channel")]]))
    else:
        context.user_data['active_channel'] = new_active
        await db_set_active_channel(uid, new_active)
        await update.message.reply_text(txt, reply_markup=kb)

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("العربية 🇸🇦", callback_data="lang_ar"), InlineKeyboardButton("English 🇬🇧", callback_data="lang_en")],
        [InlineKeyboardButton("Français 🇫🇷", callback_data="lang_fr"), InlineKeyboardButton("Türkçe 🇹🇷", callback_data="lang_tr")],
        [InlineKeyboardButton("中文 🇨🇳", callback_data="lang_zh"), InlineKeyboardButton("Русский 🇷🇺", callback_data="lang_ru")]
    ])
    await update.message.reply_text(get_text(user_id, 'welcome'), reply_markup=keyboard)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else MAIN_ADMIN_ID
    if update.callback_query:
        await update.callback_query.message.reply_text(get_text(uid, 'help'), parse_mode="Markdown")
        await update.callback_query.answer()
    elif update.message:
        await update.message.reply_text(get_text(uid, 'help'), parse_mode="Markdown")

async def developer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else MAIN_ADMIN_ID
    text = f"""👑 **معلومات المطور**
━━━━━━━━━━━━━━━━━━━━━━
🤖 **البوت:** {BOT_NAME}
📦 **الإصدار:** 7.0 (توقيت مكة + لغات متعددة)
👨‍💻 **المطور:** @Relaaaxxbot

✨ **الميزات:**
• نشر تلقائي وجدولة متقدمة
• دعم الوكيل اختيارياً
• حماية وأمان للمجموعات
• نظام نقاط ومستويات
• دعم 6 لغات (عربي، إنجليزي، فرنسي، تركي، صيني، روسي)
• نظام دعم وشكاوي مدمج

━━━━━━━━━━━━━━━━━━━━━━
📞 **طرق التواصل:**
✅ **تيليجرام:** @Relaaaxxbot
✅ **البوت:** @{BOT_USERNAME}"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 تواصل مع المطور", url=f"https://t.me/Relaaaxxbot")],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data="main")]
    ])

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

async def syncgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_force_subscribe(update, context):
        return
    if update.message is None:
        return
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("هذا الأمر يعمل فقط في المجموعات.")
        return
    user = update.effective_user
    if user is None:
        return
    if not await is_group_admin(context.bot, chat.id, user.id):
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("➕ إضافة البوت", url=f"https://t.me/{BOT_USERNAME}?startgroup")]])
        await update.message.reply_text(get_text(user.id, 'admin_only'), reply_markup=keyboard)
        return
    group_username = chat.username if chat.username else None
    is_new = await db_register_group(chat.id, chat.title or "بدون اسم", user.id, group_username)
    if is_new:
        await update.message.reply_text(f"✅ **تم تفعيل البوت في {chat.title}**\n📌 استخدم /security للإعدادات", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"ℹ️ تم تحديث معلومات {chat.title}")

async def security_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_force_subscribe(update, context):
        return
    if update.message is None:
        return
    chat = update.effective_chat
    user = update.effective_user
    uid = user.id
    if chat.type == 'private':
        await update.message.reply_text(get_text(uid, 'security_main'))
        context.user_data['waiting_for_group_security'] = True
        return
    if await is_group_admin(context.bot, chat.id, user.id) or await db_is_hidden_owner(chat.id, user.id):
        settings = await db_get_security_settings(chat.id)
        text = f"""🔐 **إعدادات أمان المجموعة**
🔗 حذف الروابط: {'✅' if settings['links'] else '❌'}
@ حذف المعرفات: {'✅' if settings['mentions'] else '❌'}
🚫 كلمات محظورة: {'✅' if settings.get('delete_banned_words', False) else '❌'}
🔊 رسالة تحذير: {'✅' if settings['warn'] else '❌'}
🚦 وضع بطيء: {'✅' if settings['slow_mode'] else '❌'}
🎯 ترحيب: {'✅' if settings['welcome_enabled'] else '❌'}
👋 وداع: {'✅' if settings['goodbye_enabled'] else '❌'}"""
        await update.message.reply_text(text, reply_markup=security_keyboard(chat.id), parse_mode="Markdown")
    else:
        await update.message.reply_text(get_text(uid, 'admin_only'))

async def register_hidden_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    user = update.effective_user
    if user is None:
        return
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ يعمل فقط في المجموعات")
        return
    if not await is_group_admin(context.bot, chat.id, user.id):
        await update.message.reply_text(get_text(user.id, 'admin_only'))
        return
    await db_register_hidden_owner_group(chat.id, user.id)
    await update.message.reply_text("✅ **تم تسجيل هذه المجموعة كمجموعة يملكها مالك مخفي!**\nالآن يمكنك استخدام /security داخل المجموعة.", parse_mode="Markdown")

async def trial_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    uid = update.effective_user.id
    if not await ensure_force_subscribe(update, context, uid):
        return
    if await db_has_used_trial(uid):
        await update.message.reply_text(get_text(uid, 'trial_used'))
        return
    if await db_has_active_subscription(uid):
        await update.message.reply_text(get_text(uid, 'already_subscribed'))
        return
    days = await db_activate_trial(uid)
    if days == 0:
        await update.message.reply_text(get_text(uid, 'already_subscribed'))
    else:
        await update.message.reply_text(get_text(uid, 'trial'))

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    uid = update.effective_user.id
    if not await ensure_force_subscribe(update, context, uid):
        return
    if await db_has_active_subscription(uid):
        days = await db_get_subscription_days_left(uid)
        await update.message.reply_text(f"✅ اشتراكك مفعل، متبقي {days} يوم\nشكراً لدعمك ❤️", parse_mode="Markdown")
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ 1 يوم - 5 نجوم", callback_data="buy_subscription_1"), InlineKeyboardButton("⭐ 2 يوم - 9 نجوم", callback_data="buy_subscription_2")],
        [InlineKeyboardButton("⭐ شهر (30 يوم) - 50 نجمة", callback_data="buy_subscription_30"), InlineKeyboardButton("⭐ 3 أشهر (90 يوم) - 120 نجمة", callback_data="buy_subscription_90")],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data="main")]
    ])
    text = get_text(uid, 'subscribe')
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

async def buy_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if query.data == "buy_subscription_1":
        days, price, title = 1, 5, "اشتراك 1 يوم"
    elif query.data == "buy_subscription_2":
        days, price, title = 2, 9, "اشتراك 2 يوم"
    elif query.data == "buy_subscription_30":
        days, price, title = 30, 50, "اشتراك شهر"
    elif query.data == "buy_subscription_90":
        days, price, title = 90, 120, "اشتراك 3 أشهر"
    else:
        await query.edit_message_text("❌ حدث خطأ")
        return
    try:
        await context.bot.send_invoice(
            chat_id=user_id, title=title, description=f"اشتراك {days} يوم",
            payload=f"sub_{days}_{price}", currency="XTR",
            prices=[LabeledPrice(label=f"اشتراك {days} يوم", amount=price)],
            need_name=False, need_phone_number=False, need_email=False,
            need_shipping_address=False, is_flexible=False
        )
    except Exception as e:
        if "Stars" in str(e):
            await query.edit_message_text("❌ الدفع بالنجوم غير مفعل حالياً، استخدم /trial", parse_mode="Markdown")
        else:
            await query.edit_message_text(f"❌ خطأ: {str(e)[:100]}")

async def pre_checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("sub_"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="بيانات غير صالحة")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.effective_user is None:
        return
    uid = update.effective_user.id
    payment = update.message.successful_payment
    try:
        parts = payment.invoice_payload.split('_')
        days = int(parts[1]) if len(parts) >= 2 else 30
    except:
        days = 30
    await db_activate_subscription(uid, days)
    await update.message.reply_text(f"✅ **تم تفعيل اشتراكك لمدة {days} يوماً!**\nشكراً لدعمك ❤️", parse_mode="Markdown")

async def show_rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    effective_user = update.effective_user
    if effective_user is None:
        return
    user_id = effective_user.id
    data = await get_rank(user_id)
    points = data['points']
    level = data['level']

    next_points = LEVEL_REQUIREMENTS.get(level + 1, points)
    points_needed = next_points - points if next_points > points else 0

    text = f"📊 **رتبتك الحالية**\n━━━━━━━━━━━━━━━━\n👤 {effective_user.first_name}\n⭐ **المستوى:** {level}\n📈 **النقاط:** {points}\n📌 **المتبقي للمستوى التالي:** {points_needed}"

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

async def show_top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_users = await get_top_users(10)
    if not top_users:
        msg = "📭 لا توجد نقاط مسجلة بعد."
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(msg, parse_mode="Markdown")
        return

    text = "🏆 **أفضل 10 مستخدمين**\n━━━━━━━━━━━━━━━━\n"
    for idx, (uid, points, level) in enumerate(top_users, 1):
        try:
            user = await context.bot.get_chat(uid)
            name = user.first_name or str(uid)
        except:
            name = str(uid)
        text += f"{idx}. {name} → المستوى {level} ({points} نقطة)\n"

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

async def panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        if not await ensure_force_subscribe(update, context):
            return
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return

    chat = update.effective_chat
    user_id = update.effective_user.id

    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text(get_text(user_id, 'group_only'))
        return

    chat_id = chat.id

    if not await is_group_admin(context.bot, chat_id, user_id) and not await db_is_hidden_owner(chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return

    current_lock_status = await is_chat_locked(chat_id)
    lock_status_text = "🔒 مقفلة" if current_lock_status else "🔓 مفتوحة"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔒 قفل المجموعة", callback_data=f"panel_lock_{chat_id}"),
         InlineKeyboardButton("🔓 فتح المجموعة", callback_data=f"panel_unlock_{chat_id}")],
        [InlineKeyboardButton("🔙 إغلاق اللوحة", callback_data="close_panel")]
    ])

    await update.message.reply_text(
        f"🔧 **لوحة تحكم المجموعة**\n━━━━━━━━━━━━━━━━\n📌 **المجموعة:** {chat.title}\n🔐 **الحالة:** {lock_status_text}\n━━━━━━━━━━━━━━━━\n\nاستخدم الأزرار للتحكم في قفل وفتح المجموعة",
        reply_markup=kb,
        parse_mode="Markdown"
    )

async def schedule_post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.effective_user is None or update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_group_admin(context.bot, chat_id, user_id) and not await db_is_hidden_owner(chat_id, user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("📝 **الاستخدام:**\n`/schedule YYYY-MM-DD HH:MM نص المنشور`", parse_mode="Markdown")
        return
    try:
        date_str = args[0]
        time_str = args[1]
        text = " ".join(args[2:])
        mecca_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        utc_dt = mecca_dt - timedelta(hours=3)
        await db_add_scheduled_post(chat_id, text, utc_dt)
        await update.message.reply_text(f"✅ **تم جدولة المنشور!**\n📅 {date_str} 🕐 {time_str} (بتوقيت مكة)", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ صيغة التاريخ أو الوقت غير صحيحة!", parse_mode="Markdown")

async def schedule_post_ui(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("📅 **جدولة منشور**\nأرسل التاريخ بالصيغة: `YYYY-MM-DD` (بتوقيت مكة)")
        context.user_data['schedule_step'] = 'waiting_date'
    else:
        await update.message.reply_text("📅 **جدولة منشور**\nأرسل التاريخ بالصيغة: `YYYY-MM-DD` (بتوقيت مكة)", parse_mode="Markdown")
        context.user_data['schedule_step'] = 'waiting_date'

async def handle_schedule_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.message.text is None:
        return
    step = context.user_data.get('schedule_step')
    if not step:
        return
    txt = update.message.text.strip()
    if step == 'waiting_date':
        try:
            datetime.strptime(txt, "%Y-%m-%d")
            context.user_data['schedule_date'] = txt
            context.user_data['schedule_step'] = 'waiting_time'
            await update.message.reply_text("🕐 أرسل الوقت بالصيغة: `HH:MM` (24 ساعة - توقيت مكة)", parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("❌ التاريخ غير صالح.")
        return
    elif step == 'waiting_time':
        try:
            datetime.strptime(txt, "%H:%M")
            context.user_data['schedule_time'] = txt
            context.user_data['schedule_step'] = 'waiting_text'
            await update.message.reply_text("📝 أرسل نص المنشور:")
        except ValueError:
            await update.message.reply_text("❌ الوقت غير صالح.")
        return
    elif step == 'waiting_text':
        date_str = context.user_data.pop('schedule_date')
        time_str = context.user_data.pop('schedule_time')
        context.user_data.pop('schedule_step')
        mecca_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        utc_dt = mecca_dt - timedelta(hours=3)
        await db_add_scheduled_post(update.effective_chat.id, txt, utc_dt)
        await update.message.reply_text(f"✅ **تم جدولة المنشور!**\n📅 {date_str} 🕐 {time_str} (بتوقيت مكة)", parse_mode="Markdown")

# ==================== أوامر الدعم ====================
async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_force_subscribe(update, context):
        return
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❓ المساعدة", callback_data="support_help"),
         InlineKeyboardButton("📋 تذكرتي", callback_data="support_ticket")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
    ])
    await update.message.reply_text(get_text(user_id, 'support_welcome'), reply_markup=keyboard, parse_mode="Markdown")
    context.user_data['support_mode'] = True

async def support_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="support_back")]])
    if update.callback_query:
        await update.callback_query.edit_message_text(get_text(user_id, 'support_help'), reply_markup=keyboard, parse_mode="Markdown")
    else:
        await update.message.reply_text(get_text(user_id, 'support_help'), reply_markup=keyboard, parse_mode="Markdown")

async def support_ticket_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ticket = await db_get_user_ticket(user_id)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="support_back")]])
    if ticket:
        ticket_num, status, created_at = ticket
        try:
            created_utc = datetime.fromisoformat(created_at)
            created_mecca = created_utc + timedelta(hours=3)
            created_str = created_mecca.strftime("%Y-%m-%d %H:%M:%S")
        except:
            created_str = created_at
        text = get_text(user_id, 'support_ticket').format(ticket_num, created_str)
    else:
        text = get_text(user_id, 'support_no_ticket')
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

async def support_back_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❓ المساعدة", callback_data="support_help"),
         InlineKeyboardButton("📋 تذكرتي", callback_data="support_ticket")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
    ])
    await update.callback_query.edit_message_text(get_text(user_id, 'support_welcome'), reply_markup=keyboard, parse_mode="Markdown")

async def support_reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MAIN_ADMIN_ID and not await db_is_bot_admin(update.effective_user.id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📝 **الاستخدام:**\n`/support_reply معرف_المستخدم نص الرد`\n\nمثال: `/support_reply 123456789 شكراً لتواصلك`", parse_mode="Markdown")
        return
    try:
        target_user_id = int(args[0])
        reply_text = " ".join(args[1:])
        await context.bot.send_message(chat_id=target_user_id, text=f"📩 **رد من فريق الدعم**\n\n{reply_text}\n\n🤍 شكراً لتواصلك معنا", parse_mode="Markdown")
        await update.message.reply_text(get_text(MAIN_ADMIN_ID, 'support_reply_sent').format(target_user_id))
        ticket_id = await db_get_last_ticket_id_for_user(target_user_id)
        if ticket_id:
            await db_mark_ticket_replied(ticket_id)
    except ValueError:
        await update.message.reply_text("❌ معرف المستخدم غير صالح")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل الإرسال: {str(e)[:100]}")

# ==================== أمر إرسال الكود ====================
async def sendcode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    allowed_user = await db_get_allowed_sendcode_user()
    if user_id != MAIN_ADMIN_ID and not await db_is_bot_admin(user_id) and (allowed_user is None or user_id != allowed_user):
        await update.message.reply_text("🔒 هذا الأمر غير متاح لك.")
        return
    try:
        await update.message.reply_document(
            document=open(__file__, 'rb'),
            filename="bot_code.py",
            caption="📁 **كود البوت الكامل**"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ فشل: {e}")

# ==================== معالج صلاحية /sendcode في لوحة الأدمن ====================
async def admin_manage_sendcode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if uid != MAIN_ADMIN_ID and not await db_is_bot_admin(uid):
        await query.edit_message_text(get_text(uid, 'admin_only'))
        return

    allowed_user = await db_get_allowed_sendcode_user()
    if allowed_user:
        current_text = get_text(uid, 'current_allowed_user').format(f"`{allowed_user}`")
    else:
        current_text = get_text(uid, 'current_allowed_user').format(get_text(uid, 'no_allowed_user'))

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(uid, 'set_new_sendcode_user'), callback_data="admin_set_sendcode_user")]
    ])
    await query.edit_message_text(
        current_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

async def admin_set_sendcode_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if uid != MAIN_ADMIN_ID and not await db_is_bot_admin(uid):
        await query.edit_message_text(get_text(uid, 'admin_only'))
        return

    await query.edit_message_text(
        get_text(uid, 'send_sendcode_user_id'),
        parse_mode="Markdown"
    )
    context.user_data['waiting_for_sendcode_user'] = True

async def handle_sendcode_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('waiting_for_sendcode_user'):
        return

    user_id_input = update.message.text.strip()
    uid = update.effective_user.id

    try:
        target_user_id = int(user_id_input)
    except ValueError:
        await update.message.reply_text(get_text(uid, 'invalid_number'))
        return

    await db_set_allowed_sendcode_user(target_user_id)

    context.user_data.pop('waiting_for_sendcode_user', None)

    await update.message.reply_text(
        get_text(uid, 'sendcode_user_set').format(target_user_id),
        parse_mode="Markdown"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]])
    await update.message.reply_text(get_text(uid, 'admin_panel'), reply_markup=keyboard, parse_mode="Markdown")

# ==================== دوال إضافة البوت ====================
async def on_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return
    bot_id = context.bot.id
    chat = update.effective_chat
    inviter = update.effective_user
    if chat.type not in ['group', 'supergroup']:
        return
    for member in update.message.new_chat_members:
        if member.id == bot_id:
            added_by_id = inviter.id if inviter else 0
            added_by_name = inviter.full_name or inviter.first_name if inviter else "غير معروف"
            chat_name = chat.title or "بدون اسم"
            await db_register_group(chat.id, chat_name, added_by_id, chat.username)
            try:
                await chat.send_message(f"🤖 **تم تفعيل البوت بنجاح!**\n📌 استخدم /security للإعدادات\n👑 للمالك المخفي: /register_hidden_owner\n🔧 لوحة التحكم: /panel", parse_mode="Markdown")
            except:
                pass
            break

async def track_chat_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if not result:
        return
    if result.new_chat_member.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
        is_new = result.old_chat_member.status in [ChatMember.LEFT, ChatMember.BANNED, ChatMember.RESTRICTED]
        if is_new:
            chat = result.chat
            added_by = result.from_user.id if result.from_user else 0
            added_by_name = result.from_user.full_name or result.from_user.first_name if result.from_user else "غير معروف"
            if chat.type == 'channel':
                await db_register_channel(chat.id, chat.title or "بدون اسم", added_by)
            elif chat.type in ['group', 'supergroup']:
                await db_register_group(chat.id, chat.title or "بدون اسم", added_by, chat.username)

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
                await context.bot.send_message(result.chat.id, msg, parse_mode="Markdown")
            except:
                pass
    elif result.old_chat_member.status == 'member' and result.new_chat_member.status in ['left', 'kicked']:
        if settings.get('goodbye_enabled'):
            user = result.old_chat_member.user
            msg = settings.get('goodbye_text', "وداعاً {user} 👋")
            msg = msg.replace('{user}', user.full_name or user.first_name).replace('{chat}', result.chat.title)
            try:
                await context.bot.send_message(result.chat.id, msg, parse_mode="Markdown")
            except:
                pass

# ==================== معالج الرسائل ====================
async def handle_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.message.text is None:
        return
    user = update.effective_user
    user_id = user.id
    username = user.full_name or user.first_name or str(user_id)
    message_text = update.message.text.strip()
    if message_text.startswith('/'):
        return
    ticket_num = await db_get_next_ticket_number()
    await db_save_ticket(user_id, username, message_text, ticket_num)
    now_utc = utc_now()
    now_mecca = now_utc + timedelta(hours=3)
    now_str = now_mecca.strftime("%Y-%m-%d %H:%M:%S")
    reply_text = get_text(user_id, 'support_received').format(ticket_num, now_str)
    await update.message.reply_text(reply_text, parse_mode="Markdown")
    notification_text = get_text(MAIN_ADMIN_ID, 'support_notification').format(username, user_id, ticket_num, now_str, message_text[:500], user_id)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 رد على المستخدم", callback_data=f"support_reply_{user_id}")],
        [InlineKeyboardButton("📋 عرض جميع التذاكر", callback_data="admin_support_tickets")]
    ])
    await context.bot.send_message(chat_id=MAIN_ADMIN_ID, text=notification_text, reply_markup=keyboard, parse_mode="Markdown")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.message.text is None:
        return
    chat = update.effective_chat
    user = update.effective_user
    uid = user.id if user else 0
    txt = update.message.text.strip()

    if user and user.is_bot:
        return

    if context.user_data.get('support_mode') and chat.type == 'private':
        await handle_support_message(update, context)
        return

    if context.user_data.get('schedule_step'):
        await handle_schedule_input(update, context)
        return

    if context.user_data.get('waiting_for_sendcode_user'):
        await handle_sendcode_user_input(update, context)
        return

    if not await check_anti_flood(update, context):
        return
    if not await check_chat_lock_before_message(update, context):
        return
    await handle_shortcuts(update, context)
    if not user.is_bot:
        await add_points(uid, update, context)
    await maybe_send_funny_response(update, context)

    if context.user_data.get('add_channel'):
        if chat.type != 'private':
            context.user_data.pop('add_channel')
            return
        new_id = await db_add_channel(uid, txt, txt)
        if new_id:
            if context.user_data.get('active_channel') is None:
                context.user_data['active_channel'] = new_id
                await db_set_active_channel(uid, new_id)
            await update.message.reply_text(get_text(uid, 'channel_added').format(txt))
        else:
            await update.message.reply_text(get_text(uid, 'channel_exists'))
        context.user_data.pop('add_channel')
        active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
        kb, txt_msg, new_active = await get_main_keyboard(uid, active)
        if kb:
            context.user_data['active_channel'] = new_active
            await db_set_active_channel(uid, new_active)
            await update.message.reply_text(txt_msg, reply_markup=kb)
        return

    if context.user_data.get('waiting_interval_min'):
        ch = context.user_data.pop('waiting_interval_min')
        try:
            minutes = int(txt)
            if minutes < 1:
                minutes = 1
            await db_save_schedule(ch, 'interval_minutes', interval_minutes=minutes)
            await update.message.reply_text(get_text(uid, 'interval_set').format(f"{minutes} دقيقة"))
        except:
            await update.message.reply_text(get_text(uid, 'invalid_number'))
        return

    if context.user_data.get('waiting_interval_hour'):
        ch = context.user_data.pop('waiting_interval_hour')
        try:
            hours = int(txt)
            if hours < 1:
                hours = 1
            await db_save_schedule(ch, 'interval_hours', interval_hours=hours)
            await update.message.reply_text(get_text(uid, 'interval_set').format(f"{hours} ساعة"))
        except:
            await update.message.reply_text(get_text(uid, 'invalid_number'))
        return

    if context.user_data.get('waiting_interval_day'):
        ch = context.user_data.pop('waiting_interval_day')
        try:
            days = int(txt)
            if days < 1:
                days = 1
            await db_save_schedule(ch, 'interval_days', interval_days=days)
            await update.message.reply_text(get_text(uid, 'interval_set').format(f"{days} يوم"))
        except:
            await update.message.reply_text(get_text(uid, 'invalid_number'))
        return

    if context.user_data.get('waiting_dates'):
        ch = context.user_data.pop('waiting_dates')
        dates_str = txt.strip()
        dates_list = [d.strip() for d in dates_str.split(',') if d.strip()]
        valid = []
        for d in dates_list:
            try:
                datetime.strptime(d, '%Y-%m-%d')
                valid.append(d)
            except:
                await update.message.reply_text(get_text(uid, 'invalid_date').format(d))
                return
        if valid:
            await db_save_schedule(ch, 'dates', specific_dates=json.dumps(valid))
            await db_set_next_publish_date(ch, None)
            await update.message.reply_text(get_text(uid, 'dates_saved').format(len(valid)))
        else:
            await update.message.reply_text(get_text(uid, 'error'))
        return

    if context.user_data.get('waiting_publish_time'):
        ch = context.user_data.pop('waiting_publish_time')
        time_str = txt.strip()
        try:
            datetime.strptime(time_str, "%H:%M")
            await db_set_publish_time(ch, time_str)
            await db_set_next_publish_date(ch, None)
            await update.message.reply_text(f"✅ تم تعيين وقت النشر إلى {time_str} (بتوقيت مكة)")
        except ValueError:
            await update.message.reply_text(get_text(uid, 'invalid_time'))
        return

    session_key = f"session_{uid}"
    if context.user_data.get(session_key) is not None:
        if txt == "/cancel":
            context.user_data.pop(session_key)
            context.user_data.pop(f"session_target_{uid}", None)
            await update.message.reply_text(get_text(uid, 'cancelled'))
            active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
            kb, txt_msg, _ = await get_main_keyboard(uid, active)
            if kb:
                await update.message.reply_text(txt_msg, reply_markup=kb)
            return
        context.user_data[session_key].append(txt)
        cur = len(context.user_data[session_key])
        target = context.user_data.get(f"session_target_{uid}", 15)
        if cur >= target:
            active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
            if not active:
                await update.message.reply_text(get_text(uid, 'error'))
                context.user_data.pop(session_key, None)
                return
            saved = await db_save_posts(active, context.user_data[session_key])
            context.user_data.pop(session_key)
            context.user_data.pop(f"session_target_{uid}", None)
            has_sub = await db_has_active_subscription(uid) or await db_has_used_trial(uid)
            auto_status = await db_auto_status(uid)
            if not has_sub:
                await update.message.reply_text(f"✅ تم حفظ {saved} منشور\n⚠️ النشر التلقائي غير مفعل بسبب عدم وجود اشتراك\nاستخدم /trial للحصول على 30 يوماً مجاناً")
            elif not auto_status:
                await update.message.reply_text(f"✅ تم حفظ {saved} منشور\n⚠️ النشر التلقائي معطل\nفعله من الإعدادات")
            else:
                await update.message.reply_text(f"✅ تم حفظ {saved} منشور\n🔄 سيتم نشرها تلقائياً (بتوقيت مكة)")
            kb, txt_msg, _ = await get_main_keyboard(uid, active)
            await update.message.reply_text(txt_msg, reply_markup=kb)
        else:
            await update.message.reply_text(f"📥 {cur}/{target}")
        return

    if context.user_data.get('waiting_for_group_banned_word'):
        chat_id = context.user_data.pop('waiting_for_group_banned_word')
        word = txt.lower().strip().split()[0] if txt.strip() else ""
        if len(word) < 2:
            await update.message.reply_text("❌ الكلمة قصيرة جداً")
            return
        if await db_add_banned_word(word, chat_id, uid):
            await update.message.reply_text(f"✅ تم إضافة {word}")
        else:
            await update.message.reply_text(f"⚠️ {word} موجودة مسبقاً")
        return

    if context.user_data.get('waiting_for_remove_group_banned_word'):
        chat_id = context.user_data.pop('waiting_for_remove_group_banned_word')
        word = txt.lower().strip()
        if await db_remove_banned_word(word, chat_id):
            await update.message.reply_text(f"✅ تم حذف {word}")
        else:
            await update.message.reply_text(f"⚠️ الكلمة {word} غير موجودة")
        return

    if context.user_data.get('waiting_for_global_banned_word'):
        context.user_data.pop('waiting_for_global_banned_word')
        word = txt.lower().strip().split()[0] if txt.strip() else ""
        if len(word) < 2:
            await update.message.reply_text("❌ الكلمة قصيرة جداً")
            return
        conn = await get_db()
        try:
            await conn.execute("INSERT INTO banned_words (word, chat_id, added_by, added_at) VALUES (?,?,?,?)", (word, -1, uid, utc_now_iso()))
            await conn.commit()
            await update.message.reply_text(f"✅ تم إضافة {word} ككلمة محظورة عامة")
        except:
            await update.message.reply_text(f"⚠️ الكلمة {word} موجودة مسبقاً")
        finally:
            await return_db(conn)
        return

    if context.user_data.get('waiting_for_remove_global_banned_word'):
        context.user_data.pop('waiting_for_remove_global_banned_word')
        word = txt.lower().strip()
        conn = await get_db()
        try:
            await conn.execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", (word, -1))
            await conn.commit()
            await update.message.reply_text(f"✅ تم حذف {word}")
        finally:
            await return_db(conn)
        return

    if context.user_data.get('admin_waiting_for_new_admin'):
        context.user_data.pop('admin_waiting_for_new_admin')
        try:
            new_admin_id = int(txt)
            await db_add_bot_admin(new_admin_id)
            await update.message.reply_text(f"✅ تمت إضافة {new_admin_id} كمشرف")
        except:
            await update.message.reply_text("❌ user_id غير صالح")
        return

    if context.user_data.get('admin_waiting_for_remove_admin'):
        context.user_data.pop('admin_waiting_for_remove_admin')
        try:
            remove_admin_id = int(txt)
            if remove_admin_id == MAIN_ADMIN_ID:
                await update.message.reply_text("❌ لا يمكن إزالة المطور الأساسي")
            else:
                await db_remove_bot_admin(remove_admin_id)
                await update.message.reply_text(f"✅ تمت إزالة {remove_admin_id} من المشرفين")
        except:
            await update.message.reply_text("❌ user_id غير صالح")
        return

    if context.user_data.get('waiting_for_update_channel'):
        context.user_data.pop('waiting_for_update_channel')
        await db_set_updates_channel(txt)
        await update.message.reply_text(f"✅ تم تعيين قناة التحديثات: {txt}")
        return

    if context.user_data.get('waiting_for_update_text'):
        context.user_data.pop('waiting_for_update_text')
        channel = await db_get_updates_channel()
        if channel:
            try:
                await context.bot.send_message(f"@{channel}", txt, parse_mode="HTML")
                await update.message.reply_text("✅ تم نشر التحديث")
            except:
                await update.message.reply_text("❌ فشل النشر، تأكد من أن البوت مشرف في القناة")
        else:
            await update.message.reply_text("❌ لم يتم تعيين قناة تحديثات بعد")
        return

    if context.user_data.get('admin_waiting_for_force_channel'):
        context.user_data.pop('admin_waiting_for_force_channel')
        await db_set_force_subscribe_channel(txt)
        await update.message.reply_text(f"✅ تم تعيين قناة الاشتراك الإجباري: {txt}")
        return

    if context.user_data.get('waiting_for_broadcast'):
        context.user_data.pop('waiting_for_broadcast')
        await update.message.reply_text("📨 جاري الإرسال...")
        conn = await get_db()
        try:
            cur = await conn.execute("SELECT user_id FROM users")
            users = await cur.fetchall()
        finally:
            await return_db(conn)
        sent = 0
        for (uid_u,) in users:
            try:
                await context.bot.send_message(uid_u, txt)
                sent += 1
            except:
                pass
            await asyncio.sleep(0.05)
        await update.message.reply_text(f"✅ تم الإرسال إلى {sent} مستخدم")
        return

    if context.user_data.get('waiting_for_group_security'):
        context.user_data.pop('waiting_for_group_security')
        identifier = txt.strip().lstrip('@')
        conn = await get_db()
        try:
            if identifier.startswith('-') or identifier.isdigit():
                cur = await conn.execute("SELECT chat_id, chat_name FROM bot_groups WHERE chat_id=?", (int(identifier),))
            else:
                cur = await conn.execute("SELECT chat_id, chat_name FROM bot_groups WHERE username=?", (identifier,))
            row = await cur.fetchone()
        finally:
            await return_db(conn)
        if not row:
            await update.message.reply_text("❌ لم يتم العثور على المجموعة")
            return
        chat_id, group_name = row
        if not await is_group_admin(context.bot, chat_id, uid) and not await db_is_hidden_owner(chat_id, uid):
            await update.message.reply_text(get_text(uid, 'not_admin'))
            return
        settings = await db_get_security_settings(chat_id)
        text = f"🔐 إعدادات أمان {group_name}\n🔗 روابط: {'✅' if settings['links'] else '❌'}\n@ معرفات: {'✅' if settings['mentions'] else '❌'}\n🚫 كلمات: {'✅' if settings.get('delete_banned_words', False) else '❌'}\n🔊 تحذير: {'✅' if settings['warn'] else '❌'}\n🚦 بطيء: {'✅' if settings['slow_mode'] else '❌'}\n🎯 ترحيب: {'✅' if settings['welcome_enabled'] else '❌'}\n👋 وداع: {'✅' if settings['goodbye_enabled'] else '❌'}"
        await update.message.reply_text(text, reply_markup=security_keyboard(chat_id), parse_mode="Markdown")
        return

    if context.user_data.get('admin_waiting_for_keyword'):
        context.user_data['admin_waiting_for_keyword'] = False
        context.user_data['admin_waiting_for_reply'] = True
        context.user_data['admin_keyword'] = txt.lower()
        await update.message.reply_text("📝 أرسل الرد الذي تريده")
        return

    if context.user_data.get('admin_waiting_for_reply'):
        context.user_data.pop('admin_waiting_for_reply')
        kw = context.user_data.pop('admin_keyword')
        reply = txt
        if kw and reply:
            await db_add_reply(kw, reply)
            await update.message.reply_text(f"✅ تم إضافة رد للكلمة {kw}")
        else:
            await update.message.reply_text("❌ حدث خطأ")
        return

    if context.user_data.get('admin_del_reply'):
        context.user_data.pop('admin_del_reply')
        kw = txt.lower()
        if await db_del_reply(kw):
            await update.message.reply_text(f"✅ تم حذف رد {kw}")
        else:
            await update.message.reply_text(f"⚠️ الكلمة {kw} غير موجودة")
        return

    if chat.type in ['group', 'supergroup'] and user and not user.is_bot:
        if not await db_check_slow_mode(chat.id, uid):
            try:
                await update.message.delete()
            except:
                pass
            return
        settings = await db_get_security_settings(chat.id)
        deleted = False
        if settings['links'] and contains_link(txt):
            deleted = True
        elif settings['mentions'] and contains_mention(txt):
            deleted = True
        elif not deleted and settings.get('delete_banned_words', False):
            banned_word = await db_contains_banned_word(txt, chat.id)
            if banned_word:
                deleted = True
        if deleted:
            try:
                await update.message.delete()
                if settings['warn']:
                    w = await update.message.reply_text("⚠️ ممنوع نشر روابط أو معرفات أو كلمات محظورة!")
                    await asyncio.sleep(3)
                    await w.delete()
            except:
                pass
            return
        reply = await db_get_reply(txt.lower())
        if reply:
            await update.message.reply_text(reply)
            if random.random() < 0.05:
                for kw in list(SMART_RESPONSES.keys())[:3]:
                    await db_update_random_reply(kw)

# ==================== حلقة النشر التلقائي ====================
async def auto_publish_loop(bot):
    await asyncio.sleep(30)
    while True:
        try:
            conn = await get_db()
            try:
                now_utc = utc_now()
                now_utc_iso = now_utc.isoformat()
                cur = await conn.execute('''
                    SELECT uc.id, uc.channel_id, u.user_id
                    FROM user_channels uc
                    JOIN users u ON uc.user_id = u.user_id
                    LEFT JOIN schedule s ON uc.id = s.channel_db_id
                    WHERE u.auto_publish=1 AND u.banned=0 AND uc.banned=0
                      AND (s.next_publish_date IS NOT NULL AND s.next_publish_date <= ?)
                ''', (now_utc_iso,))
                rows = await cur.fetchall()
                for row in rows:
                    ch_db_id, ch_tele_id, user_id = row
                    if not await db_has_active_subscription(user_id) and not await db_has_used_trial(user_id):
                        continue
                    try:
                        bot_member = await bot.get_chat_member(ch_tele_id, bot.id)
                        if bot_member.status not in ['administrator', 'creator']:
                            async with _channel_failure_lock:
                                _channel_failure_count[ch_db_id] += 1
                                if _channel_failure_count[ch_db_id] >= 3:
                                    await db_set_channel_ban(ch_db_id, True)
                            continue
                    except:
                        continue
                    post = await db_get_next_post(ch_db_id, allow_recycle=True)
                    if post:
                        try:
                            if post['media_type'] == 'photo' and post['media_file_id']:
                                await bot.send_photo(ch_tele_id, post['media_file_id'], caption=post['text'] if post['text'] else None)
                            elif post['media_type'] == 'video' and post['media_file_id']:
                                await bot.send_video(ch_tele_id, post['media_file_id'], caption=post['text'] if post['text'] else None)
                            else:
                                await bot.send_message(ch_tele_id, post['text'])
                            await db_mark_published(post['id'])
                            await db_set_last_publish(ch_db_id, utc_now())
                            await db_update_next_publish_date(ch_db_id)
                            async with _channel_failure_lock:
                                _channel_failure_count[ch_db_id] = 0
                            await asyncio.sleep(random.uniform(5, 15))
                        except Exception as e:
                            async with _channel_failure_lock:
                                _channel_failure_count[ch_db_id] += 1
                            logger.error(f"فشل النشر في {ch_tele_id}: {e}")
            finally:
                await return_db(conn)
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"خطأ في حلقة النشر: {e}")
            await asyncio.sleep(60)

# ==================== دالة تشغيل المنشورات المجدولة ====================
async def run_scheduled_posts_loop(bot):
    while True:
        await asyncio.sleep(60)
        now_utc = utc_now()
        posts = await db_get_due_scheduled_posts(now_utc)
        for post_id, chat_id, text, fail_count in posts:
            try:
                await bot.send_message(chat_id, text)
                await db_delete_scheduled_post(post_id)
            except Exception as e:
                new_fail = fail_count + 1
                await db_update_scheduled_post_fail(post_id, new_fail)
                if new_fail >= 5:
                    await db_delete_scheduled_post(post_id)
                    logger.warning(f"تم حذف منشور مجدول بعد 5 محاولات فاشلة: {post_id}")
                else:
                    logger.error(f"فشل إرسال منشور مجدول: {e}")

# ==================== دوال تنظيف السجلات القديمة ====================
async def cleanup_old_anti_flood_records():
    while True:
        await asyncio.sleep(3600)
        now = utc_now()
        expired_users = []
        for user_id, timestamps in list(_user_messages_times.items()):
            if not timestamps or (now - timestamps[-1]).total_seconds() > 600:
                expired_users.append(user_id)
        for user_id in expired_users:
            del _user_messages_times[user_id]
        if expired_users:
            logger.info(f"🧹 تم تنظيف {len(expired_users)} مستخدم من سجلات مكافحة الإغراق")

# ==================== معالج الأزرار الرئيسي الكامل ====================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    uid = query.from_user.id
    data = query.data

    # ========== معالج حذف جميع التذاكر ==========
    if data == "admin_delete_all_tickets":
        if uid != MAIN_ADMIN_ID and not await db_is_bot_admin(uid):
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
            return
        confirm_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ نعم، احذف الكل", callback_data="admin_confirm_delete_tickets"),
             InlineKeyboardButton("❌ لا، إلغاء", callback_data="admin")]
        ])
        await query.edit_message_text(get_text(uid, 'confirm_delete_tickets'), reply_markup=confirm_kb)
        return

    if data == "admin_confirm_delete_tickets":
        if uid != MAIN_ADMIN_ID and not await db_is_bot_admin(uid):
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
            return
        count = await db_delete_all_tickets()
        await query.edit_message_text(get_text(uid, 'tickets_deleted'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
        return

    # ========== أزرار اللغة ==========
    if data.startswith("lang_"):
        lang = data.split("_")[1]
        await set_user_language(uid, lang)
        await query.answer(get_text(uid, 'lang_set'))
        active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
        kb, txt, new_active = await get_main_keyboard(uid, active)
        if kb:
            context.user_data['active_channel'] = new_active
            await db_set_active_channel(uid, new_active)
            await query.edit_message_text(txt, reply_markup=kb)
        else:
            await query.edit_message_text(txt)
        return

    if data == "language":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("العربية 🇸🇦", callback_data="lang_ar"), InlineKeyboardButton("English 🇬🇧", callback_data="lang_en")],
            [InlineKeyboardButton("Français 🇫🇷", callback_data="lang_fr"), InlineKeyboardButton("Türkçe 🇹🇷", callback_data="lang_tr")],
            [InlineKeyboardButton("中文 🇨🇳", callback_data="lang_zh"), InlineKeyboardButton("Русский 🇷🇺", callback_data="lang_ru")]
        ])
        await query.edit_message_text(get_text(uid, 'welcome'), reply_markup=keyboard)
        return

    # ========== أزرار القائمة الرئيسية ==========
    if data == "main":
        active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
        kb, txt, new_active = await get_main_keyboard(uid, active)
        if kb:
            context.user_data['active_channel'] = new_active
            await db_set_active_channel(uid, new_active)
            await query.edit_message_text(txt, reply_markup=kb)
        else:
            await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'add_channel'), callback_data="add_channel")]]))
        return

    if data == "add_channel":
        context.user_data['add_channel'] = True
        await query.edit_message_text(get_text(uid, 'send_channel_id'))
        return

    if data == "list_channels":
        channels = await db_get_channels(uid)
        if not channels:
            await query.edit_message_text(get_text(uid, 'no_channels_list'))
            return
        kb = []
        for ch in channels:
            ch_id, ch_tele, ch_name, banned = ch
            display = ch_name if ch_name != ch_tele else ch_tele
            kb.append([InlineKeyboardButton(f"📢 {display}", callback_data=f"select_channel_{ch_id}"),
                       InlineKeyboardButton("🗑️ حذف", callback_data=f"delete_channel_{ch_id}")])
        kb.append([InlineKeyboardButton(get_text(uid, 'add_channel'), callback_data="add_channel")])
        kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data="main")])
        await query.edit_message_text(get_text(uid, 'channels_list'), reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("select_channel_"):
        ch_db_id = safe_int_convert(data.split("_")[-1])
        if ch_db_id is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        context.user_data['active_channel'] = ch_db_id
        await db_set_active_channel(uid, ch_db_id)
        kb, txt, _ = await get_main_keyboard(uid, ch_db_id)
        await query.edit_message_text(txt, reply_markup=kb)
        return

    if data.startswith("delete_channel_"):
        ch_db_id = safe_int_convert(data.split("_")[-1])
        if ch_db_id is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        if await db_delete_channel_by_id(uid, ch_db_id):
            await query.answer(get_text(uid, 'channel_deleted'))
            channels = await db_get_channels(uid)
            if not channels:
                await query.edit_message_text(get_text(uid, 'no_channels_list'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'add_channel'), callback_data="add_channel")]]))
            else:
                await query.edit_message_text(get_text(uid, 'channel_deleted'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="list_channels")]]))
        else:
            await query.answer(get_text(uid, 'delete_failed'), show_alert=True)
        return

    if data == "new_post_15":
        active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
        if not active:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
            return
        context.user_data[f"session_{uid}"] = []
        context.user_data[f"session_target_{uid}"] = 15
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="cancel_session")]])
        await query.edit_message_text("📥 أرسل 15 منشوراً (0/15)\n/cancel للإلغاء", reply_markup=cancel_kb)
        return

    if data == "publish_one":
        active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
        if not active:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
            return
        post = await db_get_next_post(active)
        if not post:
            await query.edit_message_text(get_text(uid, 'no_posts'))
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
            await query.edit_message_text(get_text(uid, 'post_published'))
        except Exception as e:
            await query.edit_message_text(get_text(uid, 'publish_error').format(str(e)[:100]))
        kb, txt, _ = await get_main_keyboard(uid, active)
        await query.edit_message_text(txt, reply_markup=kb)
        return

    if data == "my_stats":
        channels = await db_get_user_channels_count(uid)
        total = await db_get_user_total_posts(uid)
        unpublished = await db_get_user_unpublished_posts(uid)
        groups = await db_get_user_groups_count(uid)
        auto = get_text(uid, 'auto_on') if await db_auto_status(uid) else get_text(uid, 'auto_off')
        text = get_text(uid, 'stats').format(channels, total, unpublished, groups, auto)
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="main")]]), parse_mode="Markdown")
        return

    if data == "settings":
        auto = await db_auto_status(uid)
        btn = get_text(uid, 'disabled') if auto else get_text(uid, 'enabled')
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{btn} النشر التلقائي", callback_data="toggle_auto")],
                                   [InlineKeyboardButton(get_text(uid, 'back'), callback_data="main")]])
        await query.edit_message_text(get_text(uid, 'settings'), reply_markup=kb)
        return

    if data == "toggle_auto":
        cur = await db_auto_status(uid)
        await db_set_auto(uid, not cur)
        status = get_text(uid, 'enabled') if not cur else get_text(uid, 'disabled')
        await query.edit_message_text(get_text(uid, 'auto_toggled').format(status))
        active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
        kb, txt, _ = await get_main_keyboard(uid, active)
        await query.edit_message_text(txt, reply_markup=kb)
        return

    if data == "stats":
        active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
        if not active:
            await query.edit_message_text("⚠️ اختر قناة")
            return
        cnt = await db_unpublished_count(active)
        ch_info = await db_get_channel_info(active)
        await query.edit_message_text(f"📊 القناة: {ch_info[1]}\nمنشورات غير منشورة: {cnt}")
        return

    if data == "help":
        await help_command(update, context)
        return

    if data == "recycle_posts":
        active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
        if active:
            await db_reset_posts_to_unpublished(active, uid)
            await query.edit_message_text(get_text(uid, 'recycled'))
        else:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
        return

    if data == "my_posts":
        active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
        if not active:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
            return
        posts = await db_get_user_posts_for_channel(active, limit=15)
        if not posts:
            await query.edit_message_text(get_text(uid, 'no_posts'))
            return
        msg = get_text(uid, 'my_posts_title') + "\n"
        kb_buttons = []
        for idx, (pid, ptext, media_type) in enumerate(posts[:10], 1):
            short = re.sub('<[^>]+>', '', ptext)[:80]
            media_icon = "🖼️" if media_type == 'photo' else "🎬" if media_type == 'video' else "📝"
            msg += f"{idx}. {media_icon} {short}...\n🆔 {pid}\n\n"
            kb_buttons.append([InlineKeyboardButton(f"🗑️ حذف #{pid}", callback_data=f"delete_single_post_{pid}_{active}")])
        kb_buttons.append([InlineKeyboardButton("🗑️ حذف الكل", callback_data=f"confirm_clear_all_{active}")])
        kb_buttons.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data="main")])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb_buttons), parse_mode="Markdown")
        return

    if data.startswith("delete_single_post_"):
        parts = data.split('_')
        if len(parts) >= 4:
            post_id = safe_int_convert(parts[3])
            active = safe_int_convert(parts[4])
            if post_id is None or active is None:
                await query.answer(get_text(uid, 'error'))
                return
            if await db_delete_single_post(post_id, uid, active):
                await query.answer("✅ تم حذف المنشور", show_alert=True)
                posts = await db_get_user_posts_for_channel(active, limit=15)
                if not posts:
                    await query.edit_message_text(get_text(uid, 'no_posts'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="main")]]))
                else:
                    msg = get_text(uid, 'my_posts_title') + "\n"
                    kb_buttons = []
                    for idx, (pid, ptext, media_type) in enumerate(posts[:10], 1):
                        short = re.sub('<[^>]+>', '', ptext)[:80]
                        media_icon = "🖼️" if media_type == 'photo' else "🎬" if media_type == 'video' else "📝"
                        msg += f"{idx}. {media_icon} {short}...\n🆔 {pid}\n\n"
                        kb_buttons.append([InlineKeyboardButton(f"🗑️ حذف #{pid}", callback_data=f"delete_single_post_{pid}_{active}")])
                    kb_buttons.append([InlineKeyboardButton("🗑️ حذف الكل", callback_data=f"confirm_clear_all_{active}")])
                    kb_buttons.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data="main")])
                    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb_buttons), parse_mode="Markdown")
            else:
                await query.answer("❌ فشل الحذف")
        return

    if data.startswith("confirm_clear_all_"):
        active = safe_int_convert(data.split("_")[-1])
        if active is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ نعم", callback_data=f"clear_all_posts_{active}"),
                                   InlineKeyboardButton("❌ لا", callback_data="main")]])
        await query.edit_message_text(get_text(uid, 'confirm_delete'), reply_markup=kb)
        return

    if data.startswith("clear_all_posts_"):
        active = safe_int_convert(data.split("_")[-1])
        if active is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        conn = await get_db()
        try:
            await conn.execute("DELETE FROM posts WHERE channel_db_id=?", (active,))
            await conn.commit()
        finally:
            await return_db(conn)
        await query.answer(get_text(uid, 'deleted_all'), show_alert=True)
        kb, txt, _ = await get_main_keyboard(uid, active)
        if kb:
            await query.edit_message_text(txt, reply_markup=kb)
        else:
            await query.edit_message_text(txt)
        return

    if data == "trial":
        if not await ensure_force_subscribe(update, context, uid):
            return
        if await db_has_used_trial(uid):
            await query.edit_message_text(get_text(uid, 'trial_used'))
            return
        if await db_has_active_subscription(uid):
            await query.edit_message_text(get_text(uid, 'already_subscribed'))
            return
        await db_activate_trial(uid)
        await query.edit_message_text(get_text(uid, 'trial'))
        return

    if data == "subscribe":
        if not await ensure_force_subscribe(update, context, uid):
            return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐ 1 يوم - 5 نجوم", callback_data="buy_subscription_1"),
             InlineKeyboardButton("⭐ 2 يوم - 9 نجوم", callback_data="buy_subscription_2")],
            [InlineKeyboardButton("⭐ شهر (30) - 50 نجمة", callback_data="buy_subscription_30"),
             InlineKeyboardButton("⭐ 3 أشهر - 120 نجمة", callback_data="buy_subscription_90")],
            [InlineKeyboardButton(get_text(uid, 'back'), callback_data="main")]
        ])
        await query.edit_message_text(get_text(uid, 'subscribe'), reply_markup=kb, parse_mode="Markdown")
        return

    if data in ["buy_subscription_1", "buy_subscription_2", "buy_subscription_30", "buy_subscription_90"]:
        await buy_subscription_callback(update, context)
        return

    if data == "developer":
        await developer_command(update, context)
        return

    if data == "admin":
        if uid == MAIN_ADMIN_ID or await db_is_bot_admin(uid):
            await query.edit_message_text(get_text(uid, 'admin_panel'), reply_markup=admin_keyboard(), parse_mode="Markdown")
        return

    if data == "check_subscribe":
        enabled = await db_get_force_subscribe_status()
        channel = await db_get_force_subscribe_channel()
        if enabled and channel:
            if await is_user_subscribed(context.bot, uid, channel):
                await query.edit_message_text("✅ تم التحقق! أنت مشترك الآن.")
                active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
                kb, txt, _ = await get_main_keyboard(uid, active)
                if kb:
                    await query.edit_message_text(txt, reply_markup=kb)
                else:
                    await query.edit_message_text(txt)
            else:
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 اشترك", url=f"https://t.me/{channel.lstrip('@')}"), InlineKeyboardButton("🔄 تأكد", callback_data="check_subscribe"), InlineKeyboardButton(get_text(uid, 'back'), callback_data="main")]])
                await query.edit_message_text(f"❌ لم تشترك في @{channel.lstrip('@')}", reply_markup=kb)
        else:
            await query.edit_message_text("⚠️ الاشتراك الإجباري غير مفعل")
        return

    # ========== أزرار إدارة صلاحية sendcode ==========
    if data == "admin_manage_sendcode":
        await admin_manage_sendcode_callback(update, context)
        return

    if data == "admin_set_sendcode_user":
        await admin_set_sendcode_user_callback(update, context)
        return

    # ========== أزرار الأدمن ==========
    if data == "admin_users":
        page = 0
        users = await db_get_all_users()
        active_users = [(u, b) for u, b in users if b == 0]
        total = len(active_users)
        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        page_u = active_users[start:end]
        if not page_u:
            await query.edit_message_text("لا يوجد مستخدمون نشطون", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
            return
        kb = []
        for uid_u, _ in page_u:
            kb.append([InlineKeyboardButton(f"🔒 {uid_u}", callback_data=f"admin_toggle_user_{uid_u}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️ السابق", callback_data=f"admin_users_page_{page-1}"))
        if end < total:
            nav.append(InlineKeyboardButton("التالي ▶️", callback_data=f"admin_users_page_{page+1}"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")])
        await query.edit_message_text(f"👥 {get_text(uid, 'admin_users')} (صفحة {page + 1}/{(total + PAGE_SIZE - 1) // PAGE_SIZE})", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "admin_banned_users":
        page = 0
        users = await db_get_all_users()
        banned_users = [(u, b) for u, b in users if b == 1]
        total = len(banned_users)
        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        page_u = banned_users[start:end]
        if not page_u:
            await query.edit_message_text("لا يوجد مستخدمون محظورون", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
            return
        kb = []
        for uid_u, _ in page_u:
            kb.append([InlineKeyboardButton(f"🔓 {uid_u}", callback_data=f"admin_toggle_user_{uid_u}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️ السابق", callback_data=f"admin_banned_users_page_{page-1}"))
        if end < total:
            nav.append(InlineKeyboardButton("التالي ▶️", callback_data=f"admin_banned_users_page_{page+1}"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")])
        await query.edit_message_text(f"🚫 {get_text(uid, 'admin_banned')} (صفحة {page + 1}/{(total + PAGE_SIZE - 1) // PAGE_SIZE})", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("admin_toggle_user_"):
        target_uid = safe_int_convert(data.split("_")[-1])
        if target_uid is None:
            await query.answer(get_text(uid, 'error'), show_alert=True)
            return
        cur = await db_is_banned(target_uid)
        await db_set_ban(target_uid, not cur)
        await query.answer(f"✅ تم {'حظر' if not cur else 'إلغاء حظر'} المستخدم", show_alert=True)
        await query.edit_message_text(get_text(uid, 'admin_panel'), reply_markup=admin_keyboard())
        return

    if data == "admin_all_channels":
        page = 0
        chs = await db_all_users_channels(only_banned=False)
        total = len(chs)
        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        page_chs = chs[start:end]
        if not page_chs:
            await query.edit_message_text("لا توجد قنوات نشطة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
            return
        kb = []
        for uid_u, ch_db_id, ch_id, name, banned in page_chs:
            display = name if name != ch_id else ch_id
            kb.append([InlineKeyboardButton(f"🔒 {display} [{uid_u}]", callback_data=f"admin_toggle_channel_{ch_db_id}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️ السابق", callback_data=f"admin_all_channels_page_{page-1}"))
        if end < total:
            nav.append(InlineKeyboardButton("التالي ▶️", callback_data=f"admin_all_channels_page_{page+1}"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")])
        await query.edit_message_text(f"📡 {get_text(uid, 'admin_channels')} (صفحة {page + 1}/{(total + PAGE_SIZE - 1) // PAGE_SIZE})", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "admin_banned_channels":
        page = 0
        chs = await db_all_users_channels(only_banned=True)
        total = len(chs)
        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        page_chs = chs[start:end]
        if not page_chs:
            await query.edit_message_text("لا توجد قنوات محظورة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
            return
        kb = []
        for uid_u, ch_db_id, ch_id, name, banned in page_chs:
            display = name if name != ch_id else ch_id
            kb.append([InlineKeyboardButton(f"🔓 {display} [{uid_u}]", callback_data=f"admin_toggle_channel_{ch_db_id}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️ السابق", callback_data=f"admin_banned_channels_page_{page-1}"))
        if end < total:
            nav.append(InlineKeyboardButton("التالي ▶️", callback_data=f"admin_banned_channels_page_{page+1}"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")])
        await query.edit_message_text(f"⛔ {get_text(uid, 'admin_banned_channels')} (صفحة {page + 1}/{(total + PAGE_SIZE - 1) // PAGE_SIZE})", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("admin_toggle_channel_"):
        ch_db_id = safe_int_convert(data.split("_")[-1])
        if ch_db_id is None:
            await query.answer(get_text(uid, 'error'), show_alert=True)
            return
        cur = await db_is_channel_banned(ch_db_id)
        await db_set_channel_ban(ch_db_id, not cur)
        await query.answer(f"✅ تم {'حظر' if not cur else 'إلغاء حظر'} القناة", show_alert=True)
        await query.edit_message_text(get_text(uid, 'admin_panel'), reply_markup=admin_keyboard())
        return

    if data == "admin_groups":
        page = 0
        groups = await db_get_all_groups(only_banned=False)
        total = len(groups)
        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        page_groups = groups[start:end]
        if not page_groups:
            await query.edit_message_text("لا توجد مجموعات نشطة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
            return
        kb = []
        for chat_id, chat_name, username, added_by, added_at, banned in page_groups:
            name = (chat_name[:25] + "...") if len(chat_name) > 27 else chat_name
            kb.append([InlineKeyboardButton(f"🔒 {name}", callback_data=f"admin_toggle_group_{chat_id}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️ السابق", callback_data=f"admin_groups_page_{page-1}"))
        if end < total:
            nav.append(InlineKeyboardButton("التالي ▶️", callback_data=f"admin_groups_page_{page+1}"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")])
        await query.edit_message_text(f"📊 {get_text(uid, 'admin_groups')} (صفحة {page + 1}/{(total + PAGE_SIZE - 1) // PAGE_SIZE})", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "admin_banned_groups":
        page = 0
        groups = await db_get_all_groups(only_banned=True)
        total = len(groups)
        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        page_groups = groups[start:end]
        if not page_groups:
            await query.edit_message_text("لا توجد مجموعات محظورة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
            return
        kb = []
        for chat_id, chat_name, username, added_by, added_at, banned in page_groups:
            name = (chat_name[:25] + "...") if len(chat_name) > 27 else chat_name
            kb.append([InlineKeyboardButton(f"🔓 {name}", callback_data=f"admin_toggle_group_{chat_id}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️ السابق", callback_data=f"admin_banned_groups_page_{page-1}"))
        if end < total:
            nav.append(InlineKeyboardButton("التالي ▶️", callback_data=f"admin_banned_groups_page_{page+1}"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")])
        await query.edit_message_text(f"🚷 {get_text(uid, 'admin_banned_groups')} (صفحة {page + 1}/{(total + PAGE_SIZE - 1) // PAGE_SIZE})", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("admin_toggle_group_"):
        group_id_str = data.replace("admin_toggle_group_", "")
        if not group_id_str.startswith('-'):
            group_id_str = '-' + group_id_str
        chat_id = safe_int_convert(group_id_str)
        if chat_id is None:
            await query.answer(get_text(uid, 'error'), show_alert=True)
            return
        cur = await db_is_group_banned(chat_id)
        await db_set_group_ban(chat_id, not cur)
        await query.answer(f"✅ تم {'حظر' if not cur else 'إلغاء حظر'} المجموعة", show_alert=True)
        await query.edit_message_text(get_text(uid, 'admin_panel'), reply_markup=admin_keyboard())
        return

    # ========== أزرار قنوات البوت (تم إضافة المعالجة الكاملة) ==========
    if data == "admin_bot_channels":
        page = 0
        chs = await db_get_all_bot_channels(only_banned=False)
        total = len(chs)
        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        page_chs = chs[start:end]
        if not page_chs:
            await query.edit_message_text("لا توجد قنوات بوت نشطة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
            return
        kb = []
        for channel_id, channel_name, added_by, added_at, banned in page_chs:
            display = channel_name if channel_name != str(channel_id) else channel_id
            kb.append([InlineKeyboardButton(f"🔒 {display} [{added_by}]", callback_data=f"admin_toggle_bot_channel_{channel_id}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️ السابق", callback_data=f"admin_bot_channels_page_{page-1}"))
        if end < total:
            nav.append(InlineKeyboardButton("التالي ▶️", callback_data=f"admin_bot_channels_page_{page+1}"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")])
        await query.edit_message_text(f"📢 {get_text(uid, 'admin_bot_channels')} (صفحة {page + 1}/{(total + PAGE_SIZE - 1) // PAGE_SIZE})", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "admin_banned_bot_channels":
        page = 0
        chs = await db_get_all_bot_channels(only_banned=True)
        total = len(chs)
        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        page_chs = chs[start:end]
        if not page_chs:
            await query.edit_message_text("لا توجد قنوات بوت محظورة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
            return
        kb = []
        for channel_id, channel_name, added_by, added_at, banned in page_chs:
            display = channel_name if channel_name != str(channel_id) else channel_id
            kb.append([InlineKeyboardButton(f"🔓 {display} [{added_by}]", callback_data=f"admin_toggle_bot_channel_{channel_id}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️ السابق", callback_data=f"admin_banned_bot_channels_page_{page-1}"))
        if end < total:
            nav.append(InlineKeyboardButton("التالي ▶️", callback_data=f"admin_banned_bot_channels_page_{page+1}"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")])
        await query.edit_message_text(f"🚫 {get_text(uid, 'admin_banned_bot_channels')} (صفحة {page + 1}/{(total + PAGE_SIZE - 1) // PAGE_SIZE})", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("admin_toggle_bot_channel_"):
        channel_id_str = data.split("_")[-1]
        try:
            channel_id = int(channel_id_str)
        except:
            await query.answer(get_text(uid, 'error'), show_alert=True)
            return
        cur = await db_is_channel_bot_banned(channel_id)
        await db_set_channel_bot_ban(channel_id, not cur)
        await query.answer(f"✅ تم {'حظر' if not cur else 'إلغاء حظر'} القناة", show_alert=True)
        await query.edit_message_text(get_text(uid, 'admin_panel'), reply_markup=admin_keyboard())
        return

    if data.startswith("admin_bot_channels_page_"):
        page = int(data.split("_")[-1])
        chs = await db_get_all_bot_channels(only_banned=False)
        total = len(chs)
        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        page_chs = chs[start:end]
        if not page_chs:
            await query.edit_message_text("لا توجد قنوات", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
            return
        kb = []
        for channel_id, channel_name, added_by, added_at, banned in page_chs:
            display = channel_name if channel_name != str(channel_id) else channel_id
            kb.append([InlineKeyboardButton(f"🔒 {display} [{added_by}]", callback_data=f"admin_toggle_bot_channel_{channel_id}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️ السابق", callback_data=f"admin_bot_channels_page_{page-1}"))
        if end < total:
            nav.append(InlineKeyboardButton("التالي ▶️", callback_data=f"admin_bot_channels_page_{page+1}"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")])
        await query.edit_message_text(f"📢 {get_text(uid, 'admin_bot_channels')} (صفحة {page + 1}/{(total + PAGE_SIZE - 1) // PAGE_SIZE})", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("admin_banned_bot_channels_page_"):
        page = int(data.split("_")[-1])
        chs = await db_get_all_bot_channels(only_banned=True)
        total = len(chs)
        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        page_chs = chs[start:end]
        if not page_chs:
            await query.edit_message_text("لا توجد قنوات محظورة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
            return
        kb = []
        for channel_id, channel_name, added_by, added_at, banned in page_chs:
            display = channel_name if channel_name != str(channel_id) else channel_id
            kb.append([InlineKeyboardButton(f"🔓 {display} [{added_by}]", callback_data=f"admin_toggle_bot_channel_{channel_id}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️ السابق", callback_data=f"admin_banned_bot_channels_page_{page-1}"))
        if end < total:
            nav.append(InlineKeyboardButton("التالي ▶️", callback_data=f"admin_banned_bot_channels_page_{page+1}"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")])
        await query.edit_message_text(f"🚫 {get_text(uid, 'admin_banned_bot_channels')} (صفحة {page + 1}/{(total + PAGE_SIZE - 1) // PAGE_SIZE})", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "admin_add_admin":
        if uid != MAIN_ADMIN_ID:
            await query.edit_message_text("⚠️ هذه الخاصية للمطور الأساسي فقط", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
            return
        context.user_data['admin_waiting_for_new_admin'] = True
        await query.edit_message_text("➕ أرسل user_id للمستخدم الجديد")
        return

    if data == "admin_remove_admin":
        if uid != MAIN_ADMIN_ID:
            await query.edit_message_text("⚠️ هذه الخاصية للمطور الأساسي فقط", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
            return
        context.user_data['admin_waiting_for_remove_admin'] = True
        await query.edit_message_text("🗑️ أرسل user_id للمستخدم المراد إزالته من المشرفين")
        return

    if data == "admin_send_update":
        context.user_data['waiting_for_update_text'] = True
        await query.edit_message_text("📢 أرسل نص التحديث (HTML مسموح)")
        return

    if data == "admin_set_update_channel":
        context.user_data['waiting_for_update_channel'] = True
        await query.edit_message_text("⚙️ أرسل معرف قناة التحديثات (مثال: @my_channel)")
        return

    if data == "admin_backup_settings":
        conn = await get_db()
        try:
            cur = await conn.execute("SELECT value FROM settings WHERE key='auto_backup'")
            row = await cur.fetchone()
            auto_backup = row[0] == '1' if row else True
        finally:
            await return_db(conn)
        status = "🟢 مفعل" if auto_backup else "🔴 معطل"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{'🔴 تعطيل' if auto_backup else '🟢 تفعيل'} النسخ الاحتياطي", callback_data="admin_toggle_auto_backup")],
            [InlineKeyboardButton("💾 نسخة فورية", callback_data="admin_backup")],
            [InlineKeyboardButton("🔄 استعادة نسخة", callback_data="admin_restore_backup")],
            [InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]
        ])
        await query.edit_message_text(f"⚙️ {get_text(uid, 'backup_settings')}\nالحالة: {status}", reply_markup=kb)
        return

    if data == "admin_toggle_auto_backup":
        conn = await get_db()
        try:
            cur = await conn.execute("SELECT value FROM settings WHERE key='auto_backup'")
            row = await cur.fetchone()
            current = row[0] == '1' if row else True
            new_val = '0' if current else '1'
            await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('auto_backup', ?)", (new_val,))
            await conn.commit()
        finally:
            await return_db(conn)
        await query.answer(f"✅ تم {'تعطيل' if current else 'تفعيل'} النسخ التلقائي", show_alert=True)
        await query.edit_message_text(get_text(uid, 'admin_panel'), reply_markup=admin_keyboard())
        return

    if data == "admin_backup":
        try:
            backup_file = await create_backup()
            await query.edit_message_text(get_text(uid, 'backup_created').format(backup_file.name), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
        except Exception as e:
            await query.edit_message_text(f"❌ فشل: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
        return

    if data == "admin_restore_backup":
        backups = await list_backups()
        if not backups:
            await query.edit_message_text(get_text(uid, 'no_backups'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
            return
        kb = []
        for backup in backups[:10]:
            backup_name = backup.name.replace("backup_", "").replace(".db", "")
            kb.append([InlineKeyboardButton(f"📁 {backup_name}", callback_data=f"restore_backup_{backup.name}")])
        kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin_backup_settings")])
        await query.edit_message_text(get_text(uid, 'select_backup'), reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("restore_backup_"):
        backup_name = data.replace("restore_backup_", "")
        backup_path = BACKUP_DIR / backup_name
        if not backup_path.exists():
            await query.edit_message_text("❌ الملف غير موجود", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
            return
        try:
            await restore_backup(backup_path)
            await query.edit_message_text(get_text(uid, 'backup_restored').format(backup_name), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
        except Exception as e:
            await query.edit_message_text(f"❌ فشل الاستعادة: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))

    if data == "admin_ram":
        ram = get_ram_usage()
        text = f"🖥️ {get_text(uid, 'ram_status')}\n📊 المستخدم: {ram['used']:.1f} GB\n💾 الإجمالي: {ram['total']:.1f} GB\n📈 النسبة: {ram['percent']:.1f}%"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
        return

    if data == "admin_stats":
        total, banned, posts, groups, channels = await db_stats()
        force = await db_get_force_subscribe_status()
        text = f"📊 {get_text(uid, 'general_stats')}\n👥 المستخدمين: {total}\n🚫 محظور: {banned}\n📝 منشورات غير منشورة: {posts}\n👥 مجموعات: {groups}\n📡 قنوات المستخدمين: {channels}\n🔒 اشتراك إجباري: {'مفعل' if force else 'معطل'}"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]), parse_mode="Markdown")
        return

    if data == "admin_change_interval":
        is_admin = (uid == MAIN_ADMIN_ID or await db_is_bot_admin(uid))
        min_val = 10 if is_admin else 12
        buttons = []
        row = []
        for v in range(min_val, 61, 5):
            row.append(InlineKeyboardButton(f"{v} د", callback_data=f"set_global_interval_{v}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")])
        await query.edit_message_text(f"⏱️ {get_text(uid, 'publish_time')} (الحد الأدنى {min_val} دقيقة)", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("set_global_interval_"):
        minutes = safe_int_convert(data.split("_")[-1])
        if minutes is None:
            await query.answer(get_text(uid, 'error'), show_alert=True)
            return
        await db_set_publish_interval_seconds(minutes * 60, uid, True)
        await query.answer(f"✅ تم ضبط {minutes} دقيقة", show_alert=True)
        await query.edit_message_text(get_text(uid, 'admin_panel'), reply_markup=admin_keyboard())
        return

    if data == "admin_replies":
        await query.edit_message_text("💬 إدارة الردود", reply_markup=replies_keyboard(), parse_mode="Markdown")
        return

    if data == "admin_list_replies":
        replies = await db_get_all_replies()
        if not replies:
            await query.edit_message_text("📭 لا توجد ردود", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin_replies")]]))
            return
        msg = "📝 قائمة الردود:\n"
        for kw, rp in replies[:30]:
            msg += f"• {kw} → {rp[:40]}...\n"
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin_replies")]]))
        return

    if data == "admin_add_reply":
        context.user_data['admin_waiting_for_keyword'] = True
        await query.edit_message_text("🔤 أرسل الكلمة المفتاحية")
        return

    if data == "admin_del_reply":
        context.user_data['admin_del_reply'] = True
        await query.edit_message_text("🗑️ أرسل الكلمة المفتاحية لحذفها")
        return

    if data == "admin_broadcast":
        context.user_data['waiting_for_broadcast'] = True
        await query.edit_message_text("📨 أرسل النص الذي تريد نشره لجميع المستخدمين")
        return

    if data == "admin_updates":
        updates_text = f"🔄 **آخر تحديثات البوت** (v7.0 - توقيت مكة + لغات متعددة)\n- ضبط كامل على توقيت مكة المكرمة\n- دعم الوكيل اختيارياً\n- إضافة Foreign Keys لقاعدة البيانات\n- تحسين جميع الأزرار\n- حل مشكلة 'زر غير معروف'\n- النشر التلقائي والجدولة يعملان بتوقيت مكة\n- إضافة إدارة صلاحية /sendcode\n- إضافة 6 لغات: العربية، الإنجليزية، الفرنسية، التركية، الصينية، الروسية\n- إضافة زر حذف جميع تذاكر الدعم"
        await query.edit_message_text(updates_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
        return

    if data == "admin_force_subscribe":
        current = await db_get_force_subscribe_status()
        new_status = not current
        await db_set_force_subscribe_status(new_status)
        channel = await db_get_force_subscribe_channel()
        if new_status and not channel:
            await query.edit_message_text("⚠️ تم التفعيل لكن لم يتم تعيين قناة!\nاستخدم زر تعيين القناة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
        else:
            await query.edit_message_text(f"✅ تم {'تفعيل' if new_status else 'تعطيل'} الاشتراك الإجباري", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
        return

    if data == "admin_set_force_channel":
        context.user_data['admin_waiting_for_force_channel'] = True
        await query.edit_message_text("⚙️ أرسل معرف القناة (مثال: @my_channel)\nيجب أن يكون البوت مشرفاً فيها.")
        return

    if data == "admin_banned_words":
        await query.edit_message_text("🚫 **إدارة الكلمات المحظورة (عامة)**\n\nهذه الكلمات سيتم حذفها في كل المجموعات التي فعّلت الخاصية.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة كلمة", callback_data="admin_add_banned_word"), InlineKeyboardButton("📋 عرض الكلمات", callback_data="admin_list_banned_words")],
            [InlineKeyboardButton("🗑️ حذف كلمة", callback_data="admin_remove_banned_word"), InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]
        ]), parse_mode="Markdown")
        return

    if data == "admin_add_banned_word":
        context.user_data['waiting_for_global_banned_word'] = True
        await query.edit_message_text("➕ أرسل الكلمة التي تريد حظرها (لجميع المجموعات)")
        return

    if data == "admin_list_banned_words":
        conn = await get_db()
        try:
            cur = await conn.execute("SELECT word, added_by, added_at FROM banned_words WHERE chat_id = ?", (-1,))
            words = await cur.fetchall()
        finally:
            await return_db(conn)
        if not words:
            await query.edit_message_text("📭 لا توجد كلمات محظورة عامة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin_banned_words")]]))
            return
        msg = "🚫 **الكلمات المحظورة عامة:**\n"
        for w, by, at in words:
            msg += f"• `{w}` (أضيف بواسطة {by})\n"
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin_banned_words")]]), parse_mode="Markdown")
        return

    if data == "admin_remove_banned_word":
        context.user_data['waiting_for_remove_global_banned_word'] = True
        await query.edit_message_text("🗑️ أرسل الكلمة التي تريد حذفها")
        return

    # ========== أزرار الأمان والمجموعات ==========
    if data == "my_groups":
        groups = await db_get_user_groups(uid)
        if not groups:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ أضف البوت", url=f"https://t.me/{BOT_USERNAME}?startgroup")],
                                       [InlineKeyboardButton(get_text(uid, 'back'), callback_data="main")]])
            await query.edit_message_text(get_text(uid, 'no_groups'), reply_markup=kb, parse_mode="Markdown")
            return
        kb = []
        for chat_id, chat_name, username, banned in groups:
            name = chat_name[:27] + "..." if len(chat_name) > 30 else chat_name
            kb.append([InlineKeyboardButton(f"{'⛔' if banned else '✅'} {name}", callback_data=f"group_settings_{chat_id}")])
        kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data="main")])
        await query.edit_message_text(get_text(uid, 'my_groups_btn'), reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("group_settings_"):
        chat_id = safe_int_convert(data.split("_")[-1])
        if chat_id is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        settings = await db_get_security_settings(chat_id)
        conn = await get_db()
        try:
            cur = await conn.execute("SELECT chat_name FROM bot_groups WHERE chat_id=?", (chat_id,))
            row = await cur.fetchone()
        finally:
            await return_db(conn)
        gname = row[0] if row else str(chat_id)
        text = f"🔐 **{get_text(uid, 'group_settings_title').format(gname)}**\n🔗 {get_text(uid, 'links')}: {'✅' if settings['links'] else '❌'}\n@ {get_text(uid, 'mentions')}: {'✅' if settings['mentions'] else '❌'}\n🚫 {get_text(uid, 'banned_words')}: {'✅' if settings.get('delete_banned_words', False) else '❌'}\n🔊 {get_text(uid, 'warn')}: {'✅' if settings['warn'] else '❌'}\n🚦 {get_text(uid, 'slow_mode')}: {'✅' if settings.get('slow_mode', False) else '❌'}\n🎯 {get_text(uid, 'welcome_msg')}: {'✅' if settings.get('welcome_enabled', False) else '❌'}\n👋 {get_text(uid, 'goodbye_msg')}: {'✅' if settings.get('goodbye_enabled', False) else '❌'}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🔗 {get_text(uid, 'links')}", callback_data=f"sec_links_{chat_id}"),
             InlineKeyboardButton(f"@ {get_text(uid, 'mentions')}", callback_data=f"sec_mentions_{chat_id}")],
            [InlineKeyboardButton(f"🔊 {get_text(uid, 'warn')}", callback_data=f"sec_warn_{chat_id}"),
             InlineKeyboardButton(f"🚦 {get_text(uid, 'slow_mode')}", callback_data=f"sec_slowmode_{chat_id}")],
            [InlineKeyboardButton(f"🚫 {get_text(uid, 'banned_words')}", callback_data=f"sec_banned_words_menu_{chat_id}"),
             InlineKeyboardButton(f"🎯 {get_text(uid, 'welcome_msg')}", callback_data=f"sec_welcome_{chat_id}")],
            [InlineKeyboardButton(f"👋 {get_text(uid, 'goodbye_msg')}", callback_data=f"sec_goodbye_{chat_id}"),
             InlineKeyboardButton(get_text(uid, 'back'), callback_data="my_groups")]
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return

    if data.startswith("sec_"):
        parts = data.split('_')
        if len(parts) == 3:
            action, chat_id = parts[1], safe_int_convert(parts[2])
            if chat_id is None:
                await query.edit_message_text(get_text(uid, 'error'))
                return
            settings = await db_get_security_settings(chat_id)
            if action == "links":
                settings['links'] = not settings['links']
            elif action == "mentions":
                settings['mentions'] = not settings['mentions']
            elif action == "warn":
                settings['warn'] = not settings['warn']
            elif action == "slowmode":
                settings['slow_mode'] = not settings['slow_mode']
            await db_set_security_settings(chat_id, **settings)
            await query.edit_message_text(get_text(uid, 'updated'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="my_groups")]]))
        return

    if data.startswith("sec_banned_words_menu_"):
        chat_id = safe_int_convert(data.split("_")[-1])
        if chat_id is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        await query.edit_message_text("🚫 إدارة الكلمات المحظورة للمجموعة", reply_markup=group_banned_words_keyboard(chat_id))
        return

    if data.startswith("group_add_banned_word_"):
        chat_id = safe_int_convert(data.split("_")[-1])
        if chat_id is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        context.user_data['waiting_for_group_banned_word'] = chat_id
        await query.edit_message_text("➕ أرسل الكلمة التي تريد حظرها في هذه المجموعة")
        return

    if data.startswith("group_list_banned_words_"):
        chat_id = safe_int_convert(data.split("_")[-1])
        if chat_id is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        words = await db_get_banned_words(chat_id)
        if not words:
            await query.edit_message_text("📭 لا توجد كلمات محظورة في هذه المجموعة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=f"sec_banned_words_menu_{chat_id}")]]))
            return
        msg = "🚫 **الكلمات المحظورة في هذه المجموعة:**\n"
        for w, by, at in words:
            msg += f"• `{w}` (أضيف بواسطة {by})\n"
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=f"sec_banned_words_menu_{chat_id}")]]), parse_mode="Markdown")
        return

    if data.startswith("group_remove_banned_word_"):
        chat_id = safe_int_convert(data.split("_")[-1])
        if chat_id is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        context.user_data['waiting_for_remove_group_banned_word'] = chat_id
        await query.edit_message_text("🗑️ أرسل الكلمة التي تريد حذفها من قائمة المحظورات")
        return

    if data == "security_main":
        await query.edit_message_text(get_text(uid, 'security_main'))
        context.user_data['waiting_for_group_security'] = True
        return

    # ========== أزرار الدعم ==========
    if data == "support":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❓ المساعدة", callback_data="support_help"),
             InlineKeyboardButton("📋 تذكرتي", callback_data="support_ticket")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
        ])
        await query.edit_message_text(get_text(uid, 'support_welcome'), reply_markup=keyboard, parse_mode="Markdown")
        context.user_data['support_mode'] = True
        return

    if data == "support_help":
        await support_help_command(update, context)
        return

    if data == "support_ticket":
        await support_ticket_command(update, context)
        return

    if data == "support_back":
        await support_back_command(update, context)
        return

    if data.startswith("support_reply_"):
        target_uid = data.split("_")[2]
        await query.edit_message_text(f"📝 **للرد على المستخدم {target_uid}:**\n\nاستخدم الأمر:\n`/support_reply {target_uid} نص الرد`\n\n**مثال:**\n`/support_reply {target_uid} شكراً لتواصلك، تم حل مشكلتك`", parse_mode="Markdown")
        return

    if data == "admin_support_tickets":
        if uid != MAIN_ADMIN_ID and not await db_is_bot_admin(uid):
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
            return
        tickets = await db_get_all_tickets(limit=20)
        if not tickets:
            await query.edit_message_text("📭 لا توجد تذاكر دعم مسجلة")
            return
        text = "📋 **تذاكر الدعم**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        for tid, uid_u, username, msg, ticket_num, status, created_at in tickets:
            try:
                created_utc = datetime.fromisoformat(created_at)
                created_mecca = created_utc + timedelta(hours=3)
                created_str = created_mecca.strftime("%Y-%m-%d %H:%M")
            except:
                created_str = created_at
            status_icon = "🟡" if status == "pending" else "🟢"
            msg_preview = msg[:40] + "..." if len(msg) > 40 else msg
            text += f"\n{status_icon} #{ticket_num} | 👤 {username}\n🆔 `{uid_u}` | 📅 {created_str}\n📝 {msg_preview}\n💡 `/support_reply {uid_u} نص الرد`\n━━━━━━━━━━━━━━━━━━━━━━\n"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin")]])
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return

    # ========== أزرار الجدولة ==========
    if data == "schedule_settings":
        active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
        if not active:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
            return
        schedule = await db_get_schedule(active)
        if schedule['type'] == 'interval_minutes':
            txt = get_text(uid, 'interval_minutes').format(schedule['interval_minutes'])
        elif schedule['type'] == 'interval_hours':
            txt = get_text(uid, 'interval_hours').format(schedule['interval_hours'])
        elif schedule['type'] == 'interval_days':
            txt = get_text(uid, 'interval_days').format(schedule['interval_days'])
        elif schedule['type'] == 'days':
            days = parse_days_of_week_safe(schedule['days_of_week'])
            day_names = ['الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']
            txt = get_text(uid, 'days_week').format(', '.join([day_names[d] for d in days]) if days else get_text(uid, 'nothing'))
        else:
            dates = parse_dates_safe(schedule['specific_dates'])
            txt = get_text(uid, 'specific_dates').format(', '.join(dates) if dates else get_text(uid, 'nothing'))
        pub_time = schedule.get('publish_time', '00:00')
        txt += f"\n🕐 وقت النشر: {pub_time} (بتوقيت مكة)"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🕐 دقائق", callback_data=f"set_interval_minutes_{active}"),
             InlineKeyboardButton("🕒 ساعات", callback_data=f"set_interval_hours_{active}")],
            [InlineKeyboardButton("📆 أيام", callback_data=f"set_interval_days_{active}"),
             InlineKeyboardButton("📅 أيام أسبوع", callback_data=f"set_days_{active}")],
            [InlineKeyboardButton("🗓️ تواريخ محددة", callback_data=f"set_dates_{active}"),
             InlineKeyboardButton("⏰ وقت النشر", callback_data=f"set_publish_time_{active}")],
            [InlineKeyboardButton(get_text(uid, 'back'), callback_data="main")]
        ])
        await query.edit_message_text(get_text(uid, 'schedule_settings').format(txt), reply_markup=kb, parse_mode="Markdown")
        return

    if data.startswith("set_publish_time_"):
        ch = safe_int_convert(data.split("_")[-1])
        if ch is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        context.user_data['waiting_publish_time'] = ch
        await query.edit_message_text(get_text(uid, 'send_time'))
        return

    if data.startswith("set_interval_minutes_"):
        ch = safe_int_convert(data.split("_")[-1])
        if ch is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        context.user_data['waiting_interval_min'] = ch
        await query.edit_message_text(get_text(uid, 'send_minutes'))
        return

    if data.startswith("set_interval_hours_"):
        ch = safe_int_convert(data.split("_")[-1])
        if ch is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        context.user_data['waiting_interval_hour'] = ch
        await query.edit_message_text(get_text(uid, 'send_hours'))
        return

    if data.startswith("set_interval_days_"):
        ch = safe_int_convert(data.split("_")[-1])
        if ch is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        context.user_data['waiting_interval_day'] = ch
        await query.edit_message_text(get_text(uid, 'send_days'))
        return

    if data.startswith("set_days_"):
        ch = safe_int_convert(data.split("_")[-1])
        if ch is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        context.user_data['selected_days_ch'] = ch
        context.user_data['selected_days'] = []
        await query.edit_message_text("اختر أيام النشر (بتوقيت مكة):", reply_markup=await build_days_keyboard(uid, context))
        return

    if data.startswith("day_"):
        day = safe_int_convert(data.split("_")[1])
        if day is None:
            await query.answer(get_text(uid, 'error'))
            return
        selected = context.user_data.get('selected_days', [])
        if day in selected:
            selected.remove(day)
        else:
            selected.append(day)
        context.user_data['selected_days'] = selected
        await query.edit_message_text("اختر أيام النشر (بتوقيت مكة):", reply_markup=await build_days_keyboard(uid, context))
        return

    if data == "save_days":
        ch = context.user_data.get('selected_days_ch')
        if ch:
            days_json = json.dumps(context.user_data.get('selected_days', []))
            await db_save_schedule(ch, 'days', days_of_week=days_json)
            await db_set_next_publish_date(ch, None)
            await query.edit_message_text(get_text(uid, 'days_saved'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="schedule_settings")]]))
        else:
            await query.edit_message_text(get_text(uid, 'error'))
        return

    if data.startswith("set_dates_"):
        ch = safe_int_convert(data.split("_")[-1])
        if ch is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        context.user_data['waiting_dates'] = ch
        await query.edit_message_text(get_text(uid, 'send_dates'))
        return

    # ========== أزرار اللوحة ==========
    if data == "close_panel":
        await query.message.delete()
        return

    if data == "sec_close":
        await query.message.delete()
        return

    if data.startswith("sec_welcome_"):
        chat_id = safe_int_convert(data.split("_")[-1])
        if chat_id is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        settings = await db_get_security_settings(chat_id)
        new_status = not settings['welcome_enabled']
        settings['welcome_enabled'] = new_status
        await db_set_security_settings(chat_id, **settings)
        await query.edit_message_text(get_text(uid, 'updated'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=f"group_settings_{chat_id}")]]))
        return

    if data.startswith("sec_goodbye_"):
        chat_id = safe_int_convert(data.split("_")[-1])
        if chat_id is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        settings = await db_get_security_settings(chat_id)
        new_status = not settings['goodbye_enabled']
        settings['goodbye_enabled'] = new_status
        await db_set_security_settings(chat_id, **settings)
        await query.edit_message_text(get_text(uid, 'updated'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=f"group_settings_{chat_id}")]]))
        return

    if data.startswith("panel_lock_"):
        chat_id = safe_int_convert(data.split("_")[2])
        if chat_id is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        if await is_group_admin(context.bot, chat_id, uid) or await db_is_hidden_owner(chat_id, uid):
            await db_set_chat_lock(chat_id, True, uid)
            await query.edit_message_text(get_text(uid, 'locked'), parse_mode="Markdown")
        else:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        return

    if data.startswith("panel_unlock_"):
        chat_id = safe_int_convert(data.split("_")[2])
        if chat_id is None:
            await query.edit_message_text(get_text(uid, 'error'))
            return
        if await is_group_admin(context.bot, chat_id, uid) or await db_is_hidden_owner(chat_id, uid):
            await db_set_chat_lock(chat_id, False)
            await query.edit_message_text(get_text(uid, 'unlocked'), parse_mode="Markdown")
        else:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        return

    if data == "schedule_post_ui":
        await schedule_post_ui(update, context)
        return

    if data == "cancel_session":
        context.user_data.pop(f"session_{uid}", None)
        context.user_data.pop(f"session_target_{uid}", None)
        await query.edit_message_text("❌ تم إلغاء إضافة المنشورات.")
        active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
        kb, txt, new_active = await get_main_keyboard(uid, active)
        if kb:
            await query.edit_message_text(txt, reply_markup=kb)
        else:
            await query.edit_message_text(txt)
        return

    if data == "show_rank":
        await show_rank_command(update, context)
        return

    if data == "show_top":
        await show_top_command(update, context)
        return

    # ========== أزرار التفعيل العام ==========
    if data == "activate_all_channels":
        if uid != MAIN_ADMIN_ID and not await db_is_bot_admin(uid):
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
            return
        conn = await get_db()
        try:
            await conn.execute("UPDATE user_channels SET banned=0 WHERE banned=1")
            await conn.commit()
            await query.edit_message_text("✅ تم إلغاء حظر جميع القنوات", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]))
        finally:
            await return_db(conn)
        return

    if data == "admin_monitor_users":
        if uid != MAIN_ADMIN_ID and not await db_is_bot_admin(uid):
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
            return
        text = "📂 **مراقبة المستخدمين**\nيمكنك مراقبة نشاط المستخدمين من خلال الأزرار أعلاه."
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data="admin")]]), parse_mode="Markdown")
        return

    # إذا لم يتطابق أي من الأزرار السابقة (لن يحدث أبداً لأننا غطينا كل شيء)
    await query.edit_message_text("⚠️ زر غير معروف. هذا خطأ نادر، يرجى إبلاغ المطور.")

# ==================== معالج الأخطاء ====================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    if isinstance(error, BadRequest):
        if any(x in str(error) for x in ["Message is not modified", "Can't parse entities", "Query is too old", "Message to edit not found"]):
            return
    if isinstance(error, (TimedOut, NetworkError)):
        logger.warning("⚠️ مشكلة في الشبكة، سيتم إعادة المحاولة تلقائياً.")
        return
    if isinstance(error, Forbidden):
        logger.warning("⚠️ البوت محظور أو ليس لديه صلاحيات كافية")
        return
    error_str = str(error)
    if TOKEN in error_str:
        error_str = error_str.replace(TOKEN, "[REDACTED]")
    logger.error(f"خطأ غير متوقع: {error_str}")
    try:
        await context.bot.send_message(MAIN_ADMIN_ID, f"🚨 **خطأ في البوت**\n\n{error_str[:300]}")
    except:
        pass

# ==================== الدالة الرئيسية ====================
async def main():
    await init_db()
    await db_pool.initialize()

    if USE_PROXY:
        http_client = httpx.AsyncClient(proxy=PROXY_URL)
        request = HTTPXRequest(http_client=http_client)
        logger.info(f"✅ تم تفعيل الوكيل: {PROXY_URL}")
    else:
        request = HTTPXRequest()
        logger.info("✅ يعمل بدون وكيل")

    app = Application.builder().token(TOKEN).request(request).defaults(defaults).build()
    app.add_error_handler(error_handler)

    # إضافة معالجات الأوامر
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("syncgroup", syncgroup))
    app.add_handler(CommandHandler("security", security_command))
    app.add_handler(CommandHandler("trial", trial_command))
    app.add_handler(CommandHandler("subscribe", subscribe_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("register_hidden_owner", register_hidden_owner))
    app.add_handler(CommandHandler("rank", show_rank_command))
    app.add_handler(CommandHandler("top", show_top_command))
    app.add_handler(CommandHandler("lock", lock_chat_command))
    app.add_handler(CommandHandler("unlock", unlock_chat_command))
    app.add_handler(CommandHandler("schedule", schedule_post_command))
    app.add_handler(CommandHandler("panel", panel_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CommandHandler("support", support_command))
    app.add_handler(CommandHandler("support_reply", support_reply_command))
    app.add_handler(CommandHandler("developer", developer_command))
    app.add_handler(CommandHandler("sendcode", sendcode_command))

    app.add_handler(PreCheckoutQueryHandler(pre_checkout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(ChatMemberHandler(track_chat_add, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_bot_added))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    commands = [
        BotCommand("start", "بدء البوت / Start"),
        BotCommand("trial", "تجربة مجانية / Free trial"),
        BotCommand("subscribe", "الاشتراك / Subscribe"),
        BotCommand("syncgroup", "تفعيل المجموعة / Sync group"),
        BotCommand("security", "إعدادات الأمان / Security"),
        BotCommand("register_hidden_owner", "تسجيل مالك مخفي / Register hidden owner"),
        BotCommand("rank", "رتبتك / Rank"),
        BotCommand("top", "أفضل 10 / Top 10"),
        BotCommand("lock", "قفل المجموعة / Lock"),
        BotCommand("unlock", "فتح المجموعة / Unlock"),
        BotCommand("schedule", "جدولة منشور / Schedule"),
        BotCommand("panel", "لوحة التحكم / Panel"),
        BotCommand("language", "تغيير اللغة / Language"),
        BotCommand("support", "مركز الدعم / Support"),
        BotCommand("help", "المساعدة / Help"),
        BotCommand("developer", "المطور / Developer"),
        BotCommand("sendcode", "إرسال كود البوت / Send code"),
    ]
    await app.bot.set_my_commands(commands)

    # تشغيل المهام الخلفية
    asyncio.create_task(auto_publish_loop(app.bot))
    asyncio.create_task(auto_backup())
    asyncio.create_task(run_scheduled_posts_loop(app.bot))
    asyncio.create_task(cleanup_old_anti_flood_records())

    logger.info(f"🚀 بوت {BOT_NAME} يعمل بنجاح ✅ (توقيت مكة المكرمة - النسخة الكاملة النهائية مع إدارة صلاحية sendcode وإصلاح أزرار قنوات البوت - إضافة 6 لغات وزر حذف التذاكر)")

    try:
        await app.run_polling(allowed_updates=["message", "callback_query", "my_chat_member", "chat_member", "pre_checkout_query"])
    except KeyboardInterrupt:
        logger.info("🛑 تم إيقاف البوت بواسطة المستخدم")
    finally:
        await db_pool.close_all()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 تم إيقاف البوت")
    except Exception as e:
        logger.error(f"❌ خطأ فادح: {e}")
        sys.exit(1)
