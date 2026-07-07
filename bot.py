#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ريلاكس مانيجر - الإصدار المتكامل الكامل 20.0.3
جميع الأنظمة: تشفير، جدولة، أمان، مسابقات، ويب، إحالات، ترجمة، تذكيرات، مخفيين، NSFW، وأكثر
المطور: @RelaxMgr
"""

import os
import sys
import asyncio
import time
import re
import json
import hashlib
import base64
import io
import csv
import shutil
import logging
import sqlite3
import random
import secrets
import gzip
import tempfile
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple, Union
from collections import defaultdict
from functools import wraps
import types

# ==================== التثبيت التلقائي للمكتبات ====================
def install_pkg(pkg):
    try:
        __import__(pkg.split("==")[0])
        return True
    except ImportError:
        try:
            import subprocess
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--quiet"])
            return True
        except:
            return False

required_pkgs = [
    "python-telegram-bot>=21.0",
    "aiosqlite==0.19.0",
    "python-dotenv==1.0.0",
    "aiohttp==3.9.0",
    "deep-translator==1.11.0",
    "cryptography==41.0.7",
    "watchdog>=3.0.0",
    "cachetools==5.3.0",
    "jinja2==3.1.2",
    "bleach==6.0.0",
    "Pillow==10.0.0",
    "zstandard==0.21.0",
    "psutil==5.9.0"
]
for pkg in required_pkgs:
    install_pkg(pkg)

# ==================== استيراد المكتبات ====================
import aiosqlite
from dotenv import load_dotenv
load_dotenv()

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommand, ChatPermissions, LabeledPrice,
    ChatMember
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, PreCheckoutQueryHandler,
    ChatMemberHandler, filters
)
from telegram.error import TimedOut, NetworkError, Forbidden, BadRequest
from telegram.request import HTTPXRequest
import aiohttp
from deep_translator import GoogleTranslator
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from cachetools import TTLCache
import jinja2
import bleach
from PIL import Image
import zstandard
import aiofiles
import psutil

# ==================== الإعدادات الأساسية ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("❌ BOT_TOKEN غير موجود")
    sys.exit(1)

OWNER = int(os.getenv("OWNER_ID", "0"))
if OWNER == 0:
    print("❌ OWNER_ID غير موجود")
    sys.exit(1)

BOT_USERNAME = os.getenv("BOT_USERNAME", "bot")
BOT_NAME = os.getenv("BOT_NAME", "ريلاكس مانيجر")
PORT = int(os.getenv("PORT", "10000"))
RENDER_URL = os.getenv("RENDER_URL", "")
DB_PATH = Path("data/bot.db")
DB_PATH.parent.mkdir(exist_ok=True)
WEB_PASSWORD = os.getenv("WEB_PASSWORD", secrets.token_urlsafe(16))
WEB_USERNAME = os.getenv("WEB_USERNAME", "admin")
WEB_SECRET_KEY = os.getenv("WEB_SECRET_KEY", secrets.token_urlsafe(32))

# ==================== التشفير ====================
KEY = os.getenv("ENC_KEY")
if not KEY:
    KEY = Fernet.generate_key().decode()
fernet = Fernet(KEY.encode())

def enc(text: str) -> str:
    if not text:
        return None
    return fernet.encrypt(text.encode()).decode()

def dec(text: str) -> str:
    if not text:
        return None
    return fernet.decrypt(text.encode()).decode()

# ==================== قاعدة البيانات ====================
_db = None
async def get_db():
    global _db
    if _db is None:
        _db = await aiosqlite.connect(str(DB_PATH))
        _db.row_factory = aiosqlite.Row
        await _db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                banned INTEGER DEFAULT 0,
                language TEXT DEFAULT 'ar',
                points INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                active_channel INTEGER,
                referral_code TEXT,
                subscription_end TEXT,
                auto_publish INTEGER DEFAULT 1,
                warns INTEGER DEFAULT 0,
                trial_used INTEGER DEFAULT 0,
                auto_recycle INTEGER DEFAULT 1,
                last_daily_reward TEXT,
                last_weekly_reward TEXT,
                achievements TEXT DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel_id TEXT,
                channel_name TEXT,
                auto_publish INTEGER DEFAULT 1,
                banned INTEGER DEFAULT 0,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_db_id INTEGER,
                text TEXT,
                media_type TEXT DEFAULT 'text',
                media_file_id TEXT,
                published INTEGER DEFAULT 0,
                scheduled_time TEXT,
                fail_count INTEGER DEFAULT 0,
                views_count INTEGER DEFAULT 0,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                task_type TEXT,
                task_data TEXT,
                execute_at TEXT,
                executed INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS schedule (
                channel_db_id INTEGER PRIMARY KEY,
                schedule_type TEXT DEFAULT 'interval_minutes',
                interval_minutes INTEGER DEFAULT 12,
                interval_hours INTEGER DEFAULT 0,
                interval_days INTEGER DEFAULT 0,
                days_of_week TEXT DEFAULT '',
                specific_dates TEXT DEFAULT '',
                publish_time TEXT DEFAULT '00:00',
                cron_expression TEXT,
                next_publish_date TEXT
            );
            CREATE TABLE IF NOT EXISTS groups (
                chat_id INTEGER PRIMARY KEY,
                chat_name TEXT,
                added_by INTEGER
            );
            CREATE TABLE IF NOT EXISTS hidden_owners (
                chat_id INTEGER,
                user_id INTEGER,
                PRIMARY KEY(chat_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS hidden_admins (
                chat_id INTEGER,
                user_id INTEGER,
                added_by INTEGER,
                added_at TEXT,
                PRIMARY KEY(chat_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS group_security (
                chat_id INTEGER PRIMARY KEY,
                lock_links INTEGER DEFAULT 0,
                lock_mentions INTEGER DEFAULT 0,
                slow_mode INTEGER DEFAULT 0,
                slow_mode_seconds INTEGER DEFAULT 5,
                welcome_msg TEXT,
                goodbye_msg TEXT,
                delete_banned_words INTEGER DEFAULT 0,
                auto_penalty TEXT DEFAULT 'none',
                auto_mute_duration INTEGER DEFAULT 60
            );
            CREATE TABLE IF NOT EXISTS mod_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                admin_id INTEGER,
                target_id INTEGER,
                action TEXT,
                reason TEXT,
                duration_minutes INTEGER,
                timestamp TEXT
            );
            CREATE TABLE IF NOT EXISTS user_warnings (
                user_id INTEGER,
                chat_id INTEGER,
                warnings INTEGER DEFAULT 0,
                PRIMARY KEY(user_id, chat_id)
            );
            CREATE TABLE IF NOT EXISTS replies (
                keyword TEXT PRIMARY KEY,
                reply TEXT
            );
            CREATE TABLE IF NOT EXISTS banned_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT,
                chat_id INTEGER DEFAULT -1,
                added_by INTEGER,
                added_at TEXT,
                UNIQUE(word, chat_id)
            );
            CREATE TABLE IF NOT EXISTS contests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER,
                title TEXT,
                description TEXT,
                prize TEXT,
                end_date TEXT,
                status TEXT DEFAULT 'active',
                winner_id INTEGER,
                contest_type TEXT DEFAULT 'raffle',
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS contest_parts (
                contest_id INTEGER,
                user_id INTEGER,
                answer TEXT,
                joined_at TEXT,
                PRIMARY KEY(contest_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS contest_winners (
                contest_id INTEGER PRIMARY KEY,
                winner_id INTEGER,
                announced_at TEXT
            );
            CREATE TABLE IF NOT EXISTS referrals (
                ref_id INTEGER,
                new_id INTEGER,
                referred_at TEXT,
                is_rewarded INTEGER DEFAULT 0,
                PRIMARY KEY(ref_id, new_id)
            );
            CREATE TABLE IF NOT EXISTS referral_rewards (
                user_id INTEGER PRIMARY KEY,
                referral_count INTEGER DEFAULT 0,
                total_reward_days INTEGER DEFAULT 0,
                claimed_reward_days INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS referral_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS reminders (
                user_id INTEGER PRIMARY KEY,
                sub INTEGER DEFAULT 1,
                daily INTEGER DEFAULT 0,
                weekly INTEGER DEFAULT 1,
                days_before INTEGER DEFAULT 3,
                last_reminder_sent INTEGER DEFAULT 0,
                notification_lang TEXT DEFAULT 'ar'
            );
            CREATE TABLE IF NOT EXISTS user_translation (
                user_id INTEGER PRIMARY KEY,
                lang TEXT DEFAULT 'off'
            );
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                message TEXT,
                num INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS user_messages (
                user_id INTEGER,
                chat_id INTEGER,
                message_time TEXT,
                PRIMARY KEY(user_id, chat_id)
            );
            CREATE TABLE IF NOT EXISTS auto_reply_settings (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                only_admins INTEGER DEFAULT 0,
                ignore_bots INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS channel_stats (
                channel_db_id INTEGER PRIMARY KEY,
                total_posts INTEGER DEFAULT 0,
                published_posts INTEGER DEFAULT 0,
                total_views INTEGER DEFAULT 0,
                avg_views REAL DEFAULT 0,
                last_post_time TEXT,
                best_publish_hour INTEGER DEFAULT 0,
                best_publish_day INTEGER DEFAULT 0,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS nsfw_settings (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                threshold REAL DEFAULT 0.7,
                delete_action INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS web_sessions (
                session_id TEXT PRIMARY KEY,
                user_data TEXT,
                expires INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_posts_channel ON posts(channel_db_id, published);
            CREATE INDEX IF NOT EXISTS idx_schedule_next ON schedule(next_publish_date);
            CREATE INDEX IF NOT EXISTS idx_channels_user ON channels(user_id);
            CREATE INDEX IF NOT EXISTS idx_banned_words_chat ON banned_words(chat_id, word);
            CREATE INDEX IF NOT EXISTS idx_mod_log_chat ON mod_log(chat_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_contests_active ON contests(status, end_date);
            CREATE INDEX IF NOT EXISTS idx_referrals_ref ON referrals(ref_id);
            CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id);
            CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at);
            INSERT OR IGNORE INTO settings VALUES('publish_interval','720');
            INSERT OR IGNORE INTO settings VALUES('last_ticket','0');
            INSERT OR IGNORE INTO settings VALUES('updates_channel','');
            INSERT OR IGNORE INTO settings VALUES('force_subscribe_enabled','0');
            INSERT OR IGNORE INTO settings VALUES('force_subscribe_channel','');
            INSERT OR IGNORE INTO settings VALUES('auto_backup','1');
            INSERT OR IGNORE INTO settings VALUES('log_channel_id','');
            INSERT OR IGNORE INTO referral_settings VALUES('reward_days_per_referral','3');
            INSERT OR IGNORE INTO referral_settings VALUES('referral_bonus_points','50');
            INSERT OR IGNORE INTO referral_settings VALUES('max_referrals_per_day','5');
            INSERT OR IGNORE INTO referral_settings VALUES('welcome_bonus_points','10');
        """)
        await _db.commit()
    return _db

async def db_execute(query: str, *params) -> List[Dict]:
    db = await get_db()
    cursor = await db.execute(query, params)
    await db.commit()
    if query.strip().upper().startswith("SELECT"):
        rows = await cursor.fetchall()
        return [dict(row) for row in rows] if rows else []
    return []

async def db_execute_one(query: str, *params) -> Optional[Dict]:
    db = await get_db()
    cursor = await db.execute(query, params)
    await db.commit()
    row = await cursor.fetchone()
    return dict(row) if row else None

# ==================== نظام الترجمة ====================
class TranslationManager:
    def __init__(self):
        self.lang = {}
        self.default_lang = "ar"
        self.supported = ["ar", "en", "fr", "tr", "zh", "ru", "de", "es", "it", "pt", "ja", "ko"]
        self.load_translations()

    def load_translations(self):
        self.lang = {
            "ar": {
                "welcome": "🌿 **مرحباً بك في {bot}**\nاختر الخيار المناسب",
                "main_title": "🌿 **{bot}**\n━━━━━━━━━━━━━━━━━━\n👤 المعرف: `{uid}`\n👥 مجموعاتي: {groups}\n💎 الاشتراك: {sub}\n📡 القناة النشطة: {ch}\n📝 منشورات غير منشورة: {posts}\n⚙️ النشر التلقائي: {auto}",
                "add_ch": "➕ إضافة قناة",
                "my_ch": "📡 قنواتي",
                "settings": "⚙️ الإعدادات",
                "add_posts": "📥 إضافة 15 منشور",
                "publish_one": "📤 نشر واحد",
                "my_posts": "📋 منشوراتي",
                "recycle": "♻️ إعادة تدوير",
                "stats": "📊 إحصائياتي",
                "full_stats": "📈 إحصائيات كاملة",
                "ch_stats": "📊 إحصائيات القناة",
                "my_groups": "👥 مجموعاتي",
                "rank": "🏆 رتبتي",
                "top": "⭐ أفضل 10",
                "schedule": "⏰ جدولة منشور",
                "publish_all": "📤 نشر الكل",
                "help": "❓ المساعدة",
                "language": "🌐 اللغة",
                "trial": "🎁 تجربة مجانية",
                "subscribe": "💎 اشتراك",
                "support": "📞 الدعم",
                "referral": "🔗 الإحالات",
                "reminder": "⏰ التذكيرات",
                "translation": "🌐 الترجمة",
                "add_to_group": "➕ إضافة إلى مجموعة",
                "admin_panel": "👑 لوحة الأدمن",
                "developer": "👨‍💻 المطور",
                "updates": "📢 التحديثات",
                "contests": "🏆 المسابقات",
                "back": "🔙 رجوع",
                "subscribed": "✅ مفعل",
                "not_subscribed": "❌ غير مفعل",
                "auto_on": "مفعل",
                "auto_off": "معطل",
                "enabled": "✅ مفعل",
                "disabled": "❌ معطل",
                "no_channels": "📭 لا توجد قنوات",
                "channel_added": "✅ تم إضافة القناة {ch}",
                "channel_deleted": "✅ تم حذف القناة",
                "no_posts": "📭 لا توجد منشورات",
                "post_published": "✅ تم نشر المنشور",
                "all_posts_published": "✅ تم نشر جميع المنشورات",
                "posts_recycled": "♻️ تم إعادة تدوير المنشورات",
                "confirm_delete": "⚠️ هل أنت متأكد؟",
                "cancelled": "❌ تم الإلغاء",
                "error": "⚠️ حدث خطأ",
                "admin_only": "🔒 هذا الأمر للمشرفين فقط",
                "group_only": "🔒 هذا الأمر يعمل فقط في المجموعات",
                "locked": "🔒 تم قفل المجموعة",
                "unlocked": "🔓 تم فتح المجموعة",
                "invalid_number": "❌ رقم غير صالح",
                "invalid_date": "❌ تاريخ غير صالح",
                "invalid_time": "❌ وقت غير صالح",
                "trial_used": "❌ لقد استخدمت التجربة مسبقاً",
                "already_subscribed": "✅ لديك اشتراك فعال",
                "trial_activated": "🎁 تم تفعيل 30 يوماً مجاناً",
                "subscription_warning": "⚠️ اشتراكك ينتهي خلال {days} أيام",
                "daily_stats": "📊 تقرير يومي\nقنوات: {ch}\nمنشورات: {posts}\nغير منشورة: {unpub}\nمجموعات: {groups}",
                "weekly_report": "📈 تقرير أسبوعي\nقنوات: {ch}\nمنشورات: {posts}\nغير منشورة: {unpub}\nمجموعات: {groups}\nإحالات: {refs}",
                "translation_off": "معطلة ❌",
                "translation_on": "مفعلة ✅ إلى {lang}",
                "translation_choose": "اختر لغة الترجمة:",
                "translation_disabled": "✅ تم إيقاف الترجمة",
                "translation_enabled": "✅ تم تفعيل الترجمة إلى {lang}",
                "send_channel_id": "📡 أرسل معرف القناة (مثال: @channel أو -100123)",
                "send_minutes": "⏱️ أرسل عدد الدقائق",
                "send_hours": "⏱️ أرسل عدد الساعات",
                "send_days": "⏱️ أرسل عدد الأيام",
                "send_dates": "📅 أرسل التواريخ (YYYY-MM-DD,YY-MM-DD)",
                "send_time": "🕐 أرسل الوقت (HH:MM)",
                "schedule_saved": "✅ تم حفظ الجدولة",
                "contests_active": "🏆 المسابقات النشطة",
                "no_contests": "📭 لا توجد مسابقات",
                "contest_join": "📝 شارك في {title}",
                "contest_joined": "✅ تم التسجيل في المسابقة",
                "contest_already": "⚠️ أنت مشترك بالفعل",
                "contest_winners": "🏆 الفائزون السابقون",
                "no_winners": "📭 لا يوجد فائزون",
                "contest_created": "✅ تم إنشاء المسابقة",
                "contest_declared": "✅ تم إعلان الفائز",
                "hidden_owner_added": "✅ تم تسجيل مالك مخفي",
                "hidden_admin_added": "✅ تم إضافة مشرف مخفي",
                "hidden_admin_removed": "✅ تم إزالة مشرف مخفي",
                "hidden_admin_list": "🔒 المشرفون المخفيون:\n{list}",
                "no_hidden_admins": "📭 لا يوجد مشرفون مخفيون",
                "claim_success": "✅ تم تسجيلك كمالك مخفي",
                "claim_fail": "❌ يجب أن تكون مشرفاً",
                "referral_link": "🔗 رابط الإحالة:\n`{link}`\n👥 المحالين: {count}\n🎁 المكافآت المتاحة: {rewards} يوم",
                "reward_claimed": "🎁 تم صرف {days} يوم",
                "no_reward": "❌ لا توجد مكافآت",
                "reminder_settings": "⏰ إعدادات التذكيرات\nاشتراك: {sub}\nيومي: {daily}\nأسبوعي: {weekly}\nقبل: {days} أيام",
                "sub_reminder": "🔔 تذكير اشتراك",
                "daily_reminder": "📊 تقرير يومي",
                "weekly_reminder": "📈 تقرير أسبوعي",
                "support_welcome": "📞 مركز الدعم\nاكتب رسالتك وسنرد عليك",
                "support_ticket": "✅ تم إنشاء تذكرة #{num}",
                "ticket_replied": "✅ تم الرد على التذكرة",
                "tickets_list": "📋 التذاكر:\n{list}",
                "no_tickets": "📭 لا توجد تذاكر",
                "broadcast_sent": "📨 تم إرسال الإذاعة إلى {count} مستخدم",
                "backup_created": "💾 تم إنشاء نسخة احتياطية",
                "backup_restored": "🔄 تم استعادة النسخة",
                "export_ready": "📥 جاهز للتصدير",
                "nsfw_detected": "🚫 تم حذف محتوى غير لائق",
                "word_banned": "🚫 كلمة محظورة: {word}",
                "link_blocked": "🔗 تم حذف رابط",
                "mention_blocked": "👥 تم حذف منشن",
                "slow_mode_active": "⏱️ الوضع البطيء: {seconds} ثانية",
                "warning_given": "⚠️ تحذير {user} ({warns}/3)",
                "user_banned_auto": "🚫 تم حظر {user} تلقائياً (3 تحذيرات)",
                "user_muted": "🔇 تم كتم {user}",
                "user_unmuted": "🔊 تم فك كتم {user}",
                "user_kicked": "👢 تم طرد {user}",
                "user_banned": "🚫 تم حظر {user}",
                "user_unbanned": "✅ تم فك حظر {user}",
                "message_pinned": "📌 تم تثبيت الرسالة",
                "message_unpinned": "✅ تم إلغاء التثبيت",
                "promoted": "⭐ تم ترقية {user}",
                "demoted": "⬇️ تم تنزيل {user}",
                "purged": "🗑️ تم حذف {count} رسالة",
                "reload_success": "✅ تم تحديث جميع الملفات",
                "reload_fail": "❌ فشل التحديث",
                "ping_status": "🫀 نبض: {ping}ms\n🗄️ قاعدة البيانات: {db}\n🕐 {time}",
                "monday": "الإثنين",
                "tuesday": "الثلاثاء",
                "wednesday": "الأربعاء",
                "thursday": "الخميس",
                "friday": "الجمعة",
                "saturday": "السبت",
                "sunday": "الأحد",
                "interval_minutes": "دقائق: {val}",
                "interval_hours": "ساعات: {val}",
                "interval_days": "أيام: {val}",
                "days_week": "أيام الأسبوع: {val}",
                "specific_dates": "تواريخ محددة: {val}",
                "nothing": "لا شيء",
                "select_backup": "💾 اختر النسخة:",
                "no_backups": "📭 لا توجد نسخ احتياطية",
                "enter_admin_id": "👑 أرسل معرف المستخدم",
                "admin_added": "✅ تم إضافة المشرف",
                "admin_removed": "✅ تم إزالة المشرف",
                "cannot_remove_owner": "❌ لا يمكن إزالة المطور",
                "invalid_user_id": "❌ معرف غير صالح",
                "auto_reply_enabled": "✅ الردود التلقائية مفعلة",
                "auto_reply_disabled": "❌ الردود التلقائية معطلة",
                "auto_reply_toggle": "تبديل حالة الردود التلقائية",
                "only_admins": "المشرفين فقط",
                "everyone": "الجميع",
                "ignore_bots": "تجاهل البوتات",
                "include_bots": "شمل البوتات",
            },
            "en": {
                "welcome": "🌿 **Welcome to {bot}**\nChoose an option",
                "main_title": "🌿 **{bot}**\n━━━━━━━━━━━━━━━━━━\n👤 ID: `{uid}`\n👥 Groups: {groups}\n💎 Subscription: {sub}\n📡 Active Channel: {ch}\n📝 Unpublished: {posts}\n⚙️ Auto Publish: {auto}",
                "add_ch": "➕ Add Channel",
                "my_ch": "📡 My Channels",
                "settings": "⚙️ Settings",
                "add_posts": "📥 Add 15 Posts",
                "publish_one": "📤 Publish One",
                "my_posts": "📋 My Posts",
                "recycle": "♻️ Recycle",
                "stats": "📊 My Stats",
                "full_stats": "📈 Full Stats",
                "ch_stats": "📊 Channel Stats",
                "my_groups": "👥 My Groups",
                "rank": "🏆 My Rank",
                "top": "⭐ Top 10",
                "schedule": "⏰ Schedule Post",
                "publish_all": "📤 Publish All",
                "help": "❓ Help",
                "language": "🌐 Language",
                "trial": "🎁 Free Trial",
                "subscribe": "💎 Subscribe",
                "support": "📞 Support",
                "referral": "🔗 Referrals",
                "reminder": "⏰ Reminders",
                "translation": "🌐 Translation",
                "add_to_group": "➕ Add to Group",
                "admin_panel": "👑 Admin Panel",
                "developer": "👨‍💻 Developer",
                "updates": "📢 Updates",
                "contests": "🏆 Contests",
                "back": "🔙 Back",
                "subscribed": "✅ Active",
                "not_subscribed": "❌ Inactive",
                "auto_on": "Enabled",
                "auto_off": "Disabled",
                "enabled": "✅ Enabled",
                "disabled": "❌ Disabled",
                "no_channels": "📭 No channels",
                "channel_added": "✅ Channel {ch} added",
                "channel_deleted": "✅ Channel deleted",
                "no_posts": "📭 No posts",
                "post_published": "✅ Post published",
                "all_posts_published": "✅ All posts published",
                "posts_recycled": "♻️ Posts recycled",
                "confirm_delete": "⚠️ Are you sure?",
                "cancelled": "❌ Cancelled",
                "error": "⚠️ Error occurred",
                "admin_only": "🔒 Admins only",
                "group_only": "🔒 Groups only",
                "locked": "🔒 Group locked",
                "unlocked": "🔓 Group unlocked",
                "invalid_number": "❌ Invalid number",
                "invalid_date": "❌ Invalid date",
                "invalid_time": "❌ Invalid time",
                "trial_used": "❌ Trial already used",
                "already_subscribed": "✅ Already subscribed",
                "trial_activated": "🎁 30 days trial activated",
                "subscription_warning": "⚠️ Subscription expires in {days} days",
                "daily_stats": "📊 Daily Report\nChannels: {ch}\nPosts: {posts}\nUnpublished: {unpub}\nGroups: {groups}",
                "weekly_report": "📈 Weekly Report\nChannels: {ch}\nPosts: {posts}\nUnpublished: {unpub}\nGroups: {groups}\nReferrals: {refs}",
                "translation_off": "Disabled ❌",
                "translation_on": "Enabled ✅ to {lang}",
                "translation_choose": "Choose translation language:",
                "translation_disabled": "✅ Translation disabled",
                "translation_enabled": "✅ Translation enabled to {lang}",
                "send_channel_id": "📡 Send channel ID (e.g., @channel or -100123)",
                "send_minutes": "⏱️ Send minutes",
                "send_hours": "⏱️ Send hours",
                "send_days": "⏱️ Send days",
                "send_dates": "📅 Send dates (YYYY-MM-DD,YY-MM-DD)",
                "send_time": "🕐 Send time (HH:MM)",
                "schedule_saved": "✅ Schedule saved",
                "contests_active": "🏆 Active Contests",
                "no_contests": "📭 No contests",
                "contest_join": "📝 Join {title}",
                "contest_joined": "✅ Registered in contest",
                "contest_already": "⚠️ Already registered",
                "contest_winners": "🏆 Previous Winners",
                "no_winners": "📭 No winners",
                "contest_created": "✅ Contest created",
                "contest_declared": "✅ Winner declared",
                "hidden_owner_added": "✅ Hidden owner registered",
                "hidden_admin_added": "✅ Hidden admin added",
                "hidden_admin_removed": "✅ Hidden admin removed",
                "hidden_admin_list": "🔒 Hidden Admins:\n{list}",
                "no_hidden_admins": "📭 No hidden admins",
                "claim_success": "✅ Registered as hidden owner",
                "claim_fail": "❌ You must be an admin",
                "referral_link": "🔗 Referral Link:\n`{link}`\n👥 Referrals: {count}\n🎁 Available Rewards: {rewards} days",
                "reward_claimed": "🎁 Claimed {days} days",
                "no_reward": "❌ No rewards",
                "reminder_settings": "⏰ Reminder Settings\nSubscription: {sub}\nDaily: {daily}\nWeekly: {weekly}\nBefore: {days} days",
                "sub_reminder": "🔔 Subscription Reminder",
                "daily_reminder": "📊 Daily Report",
                "weekly_reminder": "📈 Weekly Report",
                "support_welcome": "📞 Support Center\nSend your message",
                "support_ticket": "✅ Ticket #{num} created",
                "ticket_replied": "✅ Ticket replied",
                "tickets_list": "📋 Tickets:\n{list}",
                "no_tickets": "📭 No tickets",
                "broadcast_sent": "📨 Broadcast sent to {count} users",
                "backup_created": "💾 Backup created",
                "backup_restored": "🔄 Backup restored",
                "export_ready": "📥 Export ready",
                "nsfw_detected": "🚫 Inappropriate content deleted",
                "word_banned": "🚫 Banned word: {word}",
                "link_blocked": "🔗 Link deleted",
                "mention_blocked": "👥 Mention deleted",
                "slow_mode_active": "⏱️ Slow mode: {seconds}s",
                "warning_given": "⚠️ Warning {user} ({warns}/3)",
                "user_banned_auto": "🚫 {user} auto-banned (3 warnings)",
                "user_muted": "🔇 {user} muted",
                "user_unmuted": "🔊 {user} unmuted",
                "user_kicked": "👢 {user} kicked",
                "user_banned": "🚫 {user} banned",
                "user_unbanned": "✅ {user} unbanned",
                "message_pinned": "📌 Message pinned",
                "message_unpinned": "✅ Unpinned",
                "promoted": "⭐ {user} promoted",
                "demoted": "⬇️ {user} demoted",
                "purged": "🗑️ {count} messages deleted",
                "reload_success": "✅ All files reloaded",
                "reload_fail": "❌ Reload failed",
                "ping_status": "🫀 Ping: {ping}ms\n🗄️ Database: {db}\n🕐 {time}",
                "monday": "Monday",
                "tuesday": "Tuesday",
                "wednesday": "Wednesday",
                "thursday": "Thursday",
                "friday": "Friday",
                "saturday": "Saturday",
                "sunday": "Sunday",
                "interval_minutes": "Minutes: {val}",
                "interval_hours": "Hours: {val}",
                "interval_days": "Days: {val}",
                "days_week": "Days of week: {val}",
                "specific_dates": "Specific dates: {val}",
                "nothing": "Nothing",
                "select_backup": "💾 Select backup:",
                "no_backups": "📭 No backups",
                "enter_admin_id": "👑 Send user ID",
                "admin_added": "✅ Admin added",
                "admin_removed": "✅ Admin removed",
                "cannot_remove_owner": "❌ Cannot remove owner",
                "invalid_user_id": "❌ Invalid ID",
                "auto_reply_enabled": "✅ Auto reply enabled",
                "auto_reply_disabled": "❌ Auto reply disabled",
                "auto_reply_toggle": "Toggle auto reply",
                "only_admins": "Only admins",
                "everyone": "Everyone",
                "ignore_bots": "Ignore bots",
                "include_bots": "Include bots",
            }
        }

    def get(self, user_id: int, key: str, **kwargs) -> str:
        lang = user_lang.get(user_id, "ar")
        text = self.lang.get(lang, self.lang["ar"]).get(key, key)
        try:
            return text.format(**kwargs)
        except:
            return text

translator = TranslationManager()

# ==================== نظام اللغة ====================
user_lang = {}
_lang_cache = TTLCache(maxsize=1000, ttl=300)

async def get_user_lang(user_id: int) -> str:
    if user_id in _lang_cache:
        return _lang_cache[user_id]
    row = await db_execute_one("SELECT language FROM users WHERE user_id=?", user_id)
    lang = row["language"] if row else "ar"
    _lang_cache[user_id] = lang
    user_lang[user_id] = lang
    return lang

async def set_user_lang(user_id: int, lang: str):
    await db_execute("UPDATE users SET language=? WHERE user_id=?", lang, user_id)
    _lang_cache[user_id] = lang
    user_lang[user_id] = lang

def t(user_id: int, key: str, **kwargs) -> str:
    return translator.get(user_id, key, **kwargs)

# ==================== نظام الترجمة الآلية للمنشورات ====================
class AsyncTranslator:
    def __init__(self):
        self.cache = TTLCache(maxsize=500, ttl=3600)
        self.lock = asyncio.Lock()
        self.session = None
    
    async def get_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def translate(self, text: str, target: str) -> str:
        if not text or target == "off" or target not in ["ar","en","fr","tr","zh","ru","de","es","it","pt","ja","ko"]:
            return text
        
        cache_key = hashlib.md5(f"{text}_{target}".encode()).hexdigest()
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        try:
            result = GoogleTranslator(source="auto", target=target).translate(text[:5000])
            self.cache[cache_key] = result
            return result
        except:
            return text

auto_translator = AsyncTranslator()

# ==================== دوال المساعدة ====================
def has_links(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r'https?://\S+', text))

def has_mentions(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r'@\w+', text))

def get_banned_words_from_file():
    path = Path("banned_words.txt")
    if not path.exists():
        path.write_text("# قائمة الكلمات المحظورة\nبورن\nسكس\nجنس\nعري\nخمر\nمخدرات\nحشيش\nكحول\n")
        return []
    words = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            words.append(line.lower())
    return words

def get_replies_from_file():
    path = Path("replies.json")
    if not path.exists():
        path.write_text(json.dumps({
            "مرحباً": "أهلاً بك 🤍",
            "السلام عليكم": "وعليكم السلام 🌹",
            "شكراً": "العفو",
            "كيف حالك": "الحمد لله بخير 🙏"
        }, ensure_ascii=False, indent=2))
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except:
        return {}

# ==================== مراقبة الملفات ====================
class FileWatcher(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith("banned_words.txt"):
            asyncio.create_task(reload_banned_words())
        elif event.src_path.endswith("replies.json"):
            asyncio.create_task(reload_replies())

async def reload_banned_words():
    global _bw_cache
    global _bw_cache
    global _bw_cache
    words = get_banned_words_from_file()
    for w in words:
        await db_execute("INSERT OR IGNORE INTO banned_words(word,chat_id) VALUES(?,-1)", w)
    global _bw_cache
    global _bw_cache
    _bw_cache = await load_banned_cache()
    logger.info(f"✅ تم تحديث الكلمات المحظورة: {len(words)}")

async def reload_replies():
    replies = get_replies_from_file()
    for kw, rep in replies.items():
        await db_execute("INSERT OR REPLACE INTO replies VALUES(?,?)", kw, rep)
    logger.info(f"✅ تم تحديث الردود: {len(replies)}")

_bw_cache = {}
async def load_banned_cache():
    rows = await db_execute("SELECT chat_id, word FROM banned_words")
    cache = defaultdict(list)
    for row in rows:
        cache[row["chat_id"]].append(row["word"])
    return cache

# ==================== الصلاحيات ====================
async def is_authorized(bot, chat_id: int, user_id: int) -> bool:
    if user_id == OWNER:
        return True
    if await db_execute_one("SELECT 1 FROM hidden_owners WHERE chat_id=? AND user_id=?", chat_id, user_id):
        return True
    if await db_execute_one("SELECT 1 FROM hidden_admins WHERE chat_id=? AND user_id=?", chat_id, user_id):
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ["creator", "administrator"]
    except:
        return False

async def get_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    if context.args:
        try:
            return await context.bot.get_chat(f"@{context.args[0].replace('@','')}")
        except:
            try:
                return await context.bot.get_chat(int(context.args[0]))
            except:
                return None
    return None

async def add_points(user_id: int, points: int):
    await db_execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", user_id)
    await db_execute("UPDATE users SET points=points+? WHERE user_id=?", points, user_id)
    row = await db_execute_one("SELECT points, level FROM users WHERE user_id=?", user_id)
    if row:
        level = (row["points"] // 100) + 1
        if level > row["level"]:
            await db_execute("UPDATE users SET level=? WHERE user_id=?", level, user_id)

# ==================== الاشتراك ====================
async def has_active_subscription(user_id: int) -> bool:
    row = await db_execute_one("SELECT subscription_end FROM users WHERE user_id=?", user_id)
    if row and row["subscription_end"]:
        try:
            end = datetime.fromisoformat(dec(row["subscription_end"]))
            return end > datetime.now()
        except:
            return False
    return False

async def get_subscription_days_left(user_id: int) -> int:
    row = await db_execute_one("SELECT subscription_end FROM users WHERE user_id=?", user_id)
    if row and row["subscription_end"]:
        try:
            end = datetime.fromisoformat(dec(row["subscription_end"]))
            return max(0, (end - datetime.now()).days)
        except:
            return 0
    return 0

# ==================== الأزرار الرئيسية ====================
def main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(user_id, "add_ch"), callback_data="add_ch"),
         InlineKeyboardButton(t(user_id, "my_ch"), callback_data="my_ch"),
         InlineKeyboardButton(t(user_id, "settings"), callback_data="settings")],
        [InlineKeyboardButton(t(user_id, "add_posts"), callback_data="add_posts"),
         InlineKeyboardButton(t(user_id, "publish_one"), callback_data="publish_one"),
         InlineKeyboardButton(t(user_id, "my_posts"), callback_data="my_posts")],
        [InlineKeyboardButton(t(user_id, "recycle"), callback_data="recycle"),
         InlineKeyboardButton(t(user_id, "stats"), callback_data="stats"),
         InlineKeyboardButton(t(user_id, "full_stats"), callback_data="full_stats"),
         InlineKeyboardButton(t(user_id, "ch_stats"), callback_data="ch_stats")],
        [InlineKeyboardButton(t(user_id, "rank"), callback_data="rank"),
         InlineKeyboardButton(t(user_id, "schedule"), callback_data="schedule"),
         InlineKeyboardButton(t(user_id, "top"), callback_data="top")],
        [InlineKeyboardButton(t(user_id, "publish_all"), callback_data="publish_all"),
         InlineKeyboardButton(t(user_id, "help"), callback_data="help"),
         InlineKeyboardButton(t(user_id, "language"), callback_data="language")],
        [InlineKeyboardButton(t(user_id, "trial"), callback_data="trial"),
         InlineKeyboardButton(t(user_id, "subscribe"), callback_data="subscribe"),
         InlineKeyboardButton(t(user_id, "support"), callback_data="support")],
        [InlineKeyboardButton(t(user_id, "my_groups"), callback_data="my_groups"),
         InlineKeyboardButton(t(user_id, "contests"), callback_data="contests"),
         InlineKeyboardButton(t(user_id, "referral"), callback_data="referral")],
        [InlineKeyboardButton(t(user_id, "reminder"), callback_data="reminder"),
         InlineKeyboardButton(t(user_id, "translation"), callback_data="translation"),
         InlineKeyboardButton(t(user_id, "developer"), callback_data="developer")],
        [InlineKeyboardButton(t(user_id, "add_to_group"), url=f"https://t.me/{BOT_USERNAME}?startgroup"),
         InlineKeyboardButton(t(user_id, "updates"), callback_data="updates")],
    ])

def admin_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(user_id, "admin_panel"), callback_data="admin_panel")],
        [InlineKeyboardButton("👥 المستخدمين", callback_data="adm_users"),
         InlineKeyboardButton("🚫 المحظورين", callback_data="adm_banned")],
        [InlineKeyboardButton("📡 القنوات", callback_data="adm_channels"),
         InlineKeyboardButton("📊 المجموعات", callback_data="adm_groups")],
        [InlineKeyboardButton("💬 الردود", callback_data="adm_replies"),
         InlineKeyboardButton("📋 التذاكر", callback_data="adm_tickets")],
        [InlineKeyboardButton("🏆 إنشاء مسابقة", callback_data="adm_contest"),
         InlineKeyboardButton("🏅 إعلان فائز", callback_data="declare_winner")],
        [InlineKeyboardButton("📨 إذاعة", callback_data="adm_broadcast"),
         InlineKeyboardButton("🏆 الفائزين", callback_data="winners")],
        [InlineKeyboardButton("💾 نسخ احتياطي", callback_data="adm_backup"),
         InlineKeyboardButton("📥 تصدير", callback_data="adm_export")],
        [InlineKeyboardButton("🫀 فحص النبض", callback_data="ping_status"),
         InlineKeyboardButton("🔄 تحديث", callback_data="reload_files")],
        [InlineKeyboardButton(t(user_id, "back"), callback_data="back")],
    ])

def group_settings_keyboard(chat_id: int, settings: dict) -> InlineKeyboardMarkup:
    ll = settings.get("lock_links", 0)
    lm = settings.get("lock_mentions", 0)
    slow = settings.get("slow_mode_seconds", 0)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔗 روابط: {'✅' if ll else '❌'}", callback_data=f"gset_links_{chat_id}_{1-ll}"),
         InlineKeyboardButton(f"👥 منشنات: {'✅' if lm else '❌'}", callback_data=f"gset_mentions_{chat_id}_{1-lm}")],
        [InlineKeyboardButton(f"⏱️ بطء: {slow}ث", callback_data=f"gset_slow_{chat_id}")],
        [InlineKeyboardButton("📝 ترحيب", callback_data=f"gset_welcome_{chat_id}"),
         InlineKeyboardButton("👋 وداع", callback_data=f"gset_goodbye_{chat_id}")],
        [InlineKeyboardButton("🚫 كلمات محظورة", callback_data=f"gset_banned_{chat_id}"),
         InlineKeyboardButton("💬 ردود", callback_data=f"gset_replies_{chat_id}")],
        [InlineKeyboardButton("📜 السجل", callback_data=f"gset_log_{chat_id}"),
         InlineKeyboardButton("⚖️ عقوبات", callback_data=f"gset_penalty_{chat_id}")],
        [InlineKeyboardButton(t(0, "back"), callback_data="my_groups")],
    ])

# ==================== معالجات الأوامر ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db_execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", user.id)
    lang = await get_user_lang(user.id)
    
    if context.args and context.args[0].startswith("ref_"):
        code = context.args[0][4:]
        ref = await db_execute_one("SELECT user_id FROM users WHERE referral_code=?", code)
        if ref and ref["user_id"] != user.id:
            await db_execute("INSERT OR IGNORE INTO referrals(ref_id,new_id,referred_at) VALUES(?,?,?)", 
                           ref["user_id"], user.id, datetime.now().isoformat())
            await db_execute("INSERT OR IGNORE INTO referral_rewards(user_id) VALUES(?)", ref["user_id"])
            await db_execute("UPDATE referral_rewards SET total_reward_days=total_reward_days+3 WHERE user_id=?", ref["user_id"])
            await db_execute("UPDATE referral_rewards SET referral_count=referral_count+1 WHERE user_id=?", ref["user_id"])
            await add_points(ref["user_id"], 10)
    
    title = t(user.id, "main_title", 
              bot=BOT_NAME, uid=user.id,
              groups=len(await db_execute("SELECT 1 FROM groups WHERE added_by=?", user.id)),
              sub="✅" if await has_active_subscription(user.id) else "❌",
              ch="لا توجد",
              posts=0,
              auto="مفعل")
    
    await update.message.reply_text(title, reply_markup=main_keyboard(user.id), parse_mode="MarkdownV2")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = t(uid, "help") + """
📌 الأوامر المتاحة:
/start - القائمة الرئيسية
/help - هذه المساعدة
/claim - تسجيل مالك مخفي
/addowner @user - إضافة مالك
/addadmin @user - إضافة مشرف
/remove @user - إزالة صلاحيات
/list - عرض المالكين والمشرفين
/ban @user - حظر
/unban @user - فك حظر
/mute @user - كتم
/unmute @user - فك كتم
/kick @user - طرد
/pin - تثبيت رسالة
/unpin - إلغاء تثبيت
/promote @user - ترقية
/demote @user - تنزيل
/purge عدد - حذف رسائل
/info @user - معلومات
/report - إبلاغ عن مستخدم
/warn @user - تحذير
/transfer @user - نقل الملكية
/lock_links - قفل الروابط
/unlock_links - فتح الروابط
/lock_mentions - قفل المنشنات
/unlock_mentions - فتح المنشنات
/slowmode ثواني - وضع بطيء
/welcome نص - رسالة ترحيب
/goodbye نص - رسالة وداع
/add_banned كلمة - إضافة كلمة محظورة
/remove_banned كلمة - حذف كلمة محظورة
/list_banned - عرض الكلمات المحظورة
/add_reply كلمة رد - إضافة رد
/remove_reply كلمة - حذف رد
/list_replies - عرض الردود
/log - سجل الإجراءات
/settings - إعدادات المجموعة
/reload - تحديث الملفات
/broadcast نص - إذاعة (للمطور فقط)
/panel - لوحة تحكم للعضو
"""
    await update.message.reply_text(text)

async def claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if update.effective_chat.type not in ["group", "supergroup"]:
        return await update.message.reply_text(t(uid, "group_only"))
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "claim_fail"))
    await db_execute("INSERT OR IGNORE INTO hidden_owners VALUES(?,?)", cid, uid)
    await update.message.reply_text(t(uid, "claim_success"))

async def add_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    target = await get_target(update, context)
    if not target:
        return await update.message.reply_text("/addowner @user")
    await db_execute("INSERT OR IGNORE INTO hidden_owners VALUES(?,?)", cid, target.id)
    await update.message.reply_text(t(uid, "hidden_owner_added"))

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    target = await get_target(update, context)
    if not target:
        return await update.message.reply_text("/addadmin @user")
    await db_execute("INSERT OR IGNORE INTO hidden_admins(chat_id,user_id,added_by,added_at) VALUES(?,?,?,?)",
                    cid, target.id, uid, datetime.now().isoformat())
    await update.message.reply_text(t(uid, "hidden_admin_added"))

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    target = await get_target(update, context)
    if not target:
        return await update.message.reply_text("/remove @user")
    if target.id == OWNER:
        return await update.message.reply_text(t(uid, "cannot_remove_owner"))
    await db_execute("DELETE FROM hidden_owners WHERE chat_id=? AND user_id=?", cid, target.id)
    await db_execute("DELETE FROM hidden_admins WHERE chat_id=? AND user_id=?", cid, target.id)
    await update.message.reply_text(t(uid, "hidden_admin_removed"))

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    owners = await db_execute("SELECT user_id FROM hidden_owners WHERE chat_id=?", cid)
    admins = await db_execute("SELECT user_id FROM hidden_admins WHERE chat_id=?", cid)
    text = "👑 الملاك المخفيون:\n"
    for o in owners:
        text += f"• {o['user_id']}\n"
    text += "\n🛡️ المشرفون المخفيون:\n"
    for a in admins:
        text += f"• {a['user_id']}\n"
    await update.message.reply_text(text or t(0, "no_hidden_admins"))

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    target = await get_target(update, context)
    if not target:
        return await update.message.reply_text("📝 بالرد أو /ban @user")
    try:
        await context.bot.ban_chat_member(cid, target.id)
        await db_execute("INSERT INTO mod_log(chat_id,admin_id,target_id,action,reason,timestamp) VALUES(?,?,?,?,?,?)",
                        cid, uid, target.id, "ban", "حظر", datetime.now().isoformat())
        await update.message.reply_text(t(uid, "user_banned").format(user=target.first_name))
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    if not context.args:
        return await update.message.reply_text("/unban @user")
    try:
        target = await context.bot.get_chat(f"@{context.args[0].replace('@','')}")
        await context.bot.unban_chat_member(cid, target.id)
        await update.message.reply_text(t(uid, "user_unbanned").format(user=target.first_name))
    except:
        await update.message.reply_text(t(uid, "error"))

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    target = await get_target(update, context)
    if not target:
        return await update.message.reply_text("📝 بالرد أو /mute @user")
    try:
        await context.bot.restrict_chat_member(cid, target.id, ChatPermissions(can_send_messages=False))
        await db_execute("INSERT INTO mod_log(chat_id,admin_id,target_id,action,reason,timestamp) VALUES(?,?,?,?,?,?)",
                        cid, uid, target.id, "mute", "كتم", datetime.now().isoformat())
        await update.message.reply_text(t(uid, "user_muted").format(user=target.first_name))
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    target = await get_target(update, context)
    if not target:
        return await update.message.reply_text("/unmute @user")
    try:
        perms = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        )
        await context.bot.restrict_chat_member(cid, target.id, perms)
        await update.message.reply_text(t(uid, "user_unmuted").format(user=target.first_name))
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    target = await get_target(update, context)
    if not target:
        return await update.message.reply_text("📝 بالرد أو /kick @user")
    try:
        await context.bot.ban_chat_member(cid, target.id)
        await context.bot.unban_chat_member(cid, target.id)
        await db_execute("INSERT INTO mod_log(chat_id,admin_id,target_id,action,reason,timestamp) VALUES(?,?,?,?,?,?)",
                        cid, uid, target.id, "kick", "طرد", datetime.now().isoformat())
        await update.message.reply_text(t(uid, "user_kicked").format(user=target.first_name))
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def pin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    if not update.message.reply_to_message:
        return await update.message.reply_text("📝 بالرد على الرسالة")
    try:
        await context.bot.pin_chat_message(cid, update.message.reply_to_message.message_id)
        await update.message.reply_text(t(uid, "message_pinned"))
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def unpin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    try:
        await context.bot.unpin_chat_message(cid)
        await update.message.reply_text(t(uid, "message_unpinned"))
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def promote_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    target = await get_target(update, context)
    if not target:
        return await update.message.reply_text("/promote @user")
    try:
        await context.bot.promote_chat_member(
            cid, target.id,
            can_manage_chat=True,
            can_delete_messages=True,
            can_restrict_members=True,
            can_promote_members=True,
            can_change_info=True,
            can_invite_users=True,
            can_pin_messages=True
        )
        await update.message.reply_text(t(uid, "promoted").format(user=target.first_name))
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def demote_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    target = await get_target(update, context)
    if not target:
        return await update.message.reply_text("/demote @user")
    try:
        await context.bot.promote_chat_member(
            cid, target.id,
            can_manage_chat=False,
            can_delete_messages=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False
        )
        await update.message.reply_text(t(uid, "demoted").format(user=target.first_name))
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def purge_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    try:
        count = int(context.args[0]) if context.args else 10
    except:
        count = 10
    count = min(count, 100)
    try:
        deleted = 0
        async for msg in context.bot.get_chat_history(cid, limit=count):
            try:
                await msg.delete()
                deleted += 1
            except:
                pass
        await update.message.reply_text(t(uid, "purged").format(count=deleted))
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await get_target(update, context)
    if target:
        warns = await db_execute_one("SELECT warnings FROM user_warnings WHERE user_id=? AND chat_id=?", 
                                     target.id, update.effective_chat.id)
        w = warns["warnings"] if warns else 0
        sub_days = await get_subscription_days_left(target.id)
        text = f"👤 {target.first_name}\n🆔 {target.id}\n⚠️ تحذيرات: {w}/3\n💎 اشتراك: {sub_days} يوم"
        if target.username:
            text += f"\n📌 @{target.username}"
        await update.message.reply_text(text)
    else:
        chat = update.effective_chat
        text = f"📊 {chat.title}\n🆔 {chat.id}\n👥 النوع: {chat.type}"
        if chat.username:
            text += f"\n📌 @{chat.username}"
        await update.message.reply_text(text)

async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    target = await get_target(update, context)
    if not target:
        return await update.message.reply_text("📝 بالرد أو /warn @user")
    
    await db_execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", target.id)
    await db_execute("INSERT OR IGNORE INTO user_warnings(user_id,chat_id,warnings) VALUES(?,?,0)", target.id, cid)
    await db_execute("UPDATE user_warnings SET warnings=warnings+1 WHERE user_id=? AND chat_id=?", target.id, cid)
    
    row = await db_execute_one("SELECT warnings FROM user_warnings WHERE user_id=? AND chat_id=?", target.id, cid)
    warns = row["warnings"] if row else 0
    
    await db_execute("INSERT INTO mod_log(chat_id,admin_id,target_id,action,reason,timestamp) VALUES(?,?,?,?,?,?)",
                    cid, uid, target.id, "warn", f"تحذير {warns}/3", datetime.now().isoformat())
    
    if warns >= 3:
        try:
            await context.bot.ban_chat_member(cid, target.id)
            await update.message.reply_text(t(uid, "user_banned_auto").format(user=target.first_name))
        except:
            await update.message.reply_text(f"⚠️ 3 تحذيرات لـ {target.first_name}، لكن فشل الحظر")
    else:
        await update.message.reply_text(t(uid, "warning_given").format(user=target.first_name, warns=warns))

async def transfer_ownership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    target = await get_target(update, context)
    if not target:
        return await update.message.reply_text("/transfer @user")
    await db_execute("DELETE FROM hidden_owners WHERE chat_id=?", cid)
    await db_execute("INSERT INTO hidden_owners VALUES(?,?)", cid, target.id)
    await update.message.reply_text(f"👑 تم نقل الملكية إلى {target.first_name}")

async def lock_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    await db_execute("INSERT OR IGNORE INTO group_security(chat_id) VALUES(?)", cid)
    await db_execute("UPDATE group_security SET lock_links=1 WHERE chat_id=?", cid)
    await update.message.reply_text("🔗 تم قفل الروابط")

async def unlock_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    await db_execute("UPDATE group_security SET lock_links=0 WHERE chat_id=?", cid)
    await update.message.reply_text("🔗 تم فتح الروابط")

async def lock_mentions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    await db_execute("INSERT OR IGNORE INTO group_security(chat_id) VALUES(?)", cid)
    await db_execute("UPDATE group_security SET lock_mentions=1 WHERE chat_id=?", cid)
    await update.message.reply_text("👥 تم قفل المنشنات")

async def unlock_mentions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    await db_execute("UPDATE group_security SET lock_mentions=0 WHERE chat_id=?", cid)
    await update.message.reply_text("👥 تم فتح المنشنات")

async def slowmode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    try:
        seconds = int(context.args[0]) if context.args else 0
    except:
        return await update.message.reply_text("/slowmode 5")
    if seconds < 0:
        seconds = 0
    await db_execute("INSERT OR IGNORE INTO group_security(chat_id) VALUES(?)", cid)
    await db_execute("UPDATE group_security SET slow_mode=?, slow_mode_seconds=? WHERE chat_id=?", 
                    seconds > 0, seconds, cid)
    await update.message.reply_text(t(uid, "slow_mode_active").format(seconds=seconds))

async def welcome_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    msg = " ".join(context.args) if context.args else ""
    await db_execute("INSERT OR IGNORE INTO group_security(chat_id) VALUES(?)", cid)
    await db_execute("UPDATE group_security SET welcome_msg=? WHERE chat_id=?", msg, cid)
    await update.message.reply_text("✅ تم تحديث رسالة الترحيب")

async def goodbye_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    msg = " ".join(context.args) if context.args else ""
    await db_execute("INSERT OR IGNORE INTO group_security(chat_id) VALUES(?)", cid)
    await db_execute("UPDATE group_security SET goodbye_msg=? WHERE chat_id=?", msg, cid)
    await update.message.reply_text("✅ تم تحديث رسالة الوداع")

async def add_banned_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _bw_cache
    global _bw_cache
    global _bw_cache
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    if not context.args:
        return await update.message.reply_text("/add_banned كلمة")
    word = context.args[0].lower()
    await db_execute("INSERT OR IGNORE INTO banned_words(word,chat_id,added_by,added_at) VALUES(?,?,?,?)",
                    word, cid, uid, datetime.now().isoformat())
    global _bw_cache
    global _bw_cache
    _bw_cache = await load_banned_cache()
    await update.message.reply_text(f"✅ تم إضافة: {word}")

async def remove_banned_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _bw_cache
    global _bw_cache
    global _bw_cache
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    if not context.args:
        return await update.message.reply_text("/remove_banned كلمة")
    word = context.args[0].lower()
    global _bw_cache
    await db_execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", word, cid)
    global _bw_cache
    _bw_cache = await load_banned_cache()
    await update.message.reply_text(f"✅ تم حذف: {word}")

async def list_banned_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    words = await db_execute("SELECT word FROM banned_words WHERE chat_id=? OR chat_id=-1", cid)
    if not words:
        return await update.message.reply_text("📭 لا توجد كلمات محظورة")
    text = "🚫 الكلمات المحظورة:\n" + ", ".join(w["word"] for w in words)
    await update.message.reply_text(text)

async def add_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_authorized(context.bot, update.effective_chat.id, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    if len(context.args) < 2:
        return await update.message.reply_text("/add_reply كلمة رد")
    keyword = context.args[0].lower()
    reply = " ".join(context.args[1:])
    await db_execute("INSERT OR REPLACE INTO replies VALUES(?,?)", keyword, reply)
    await update.message.reply_text(f"✅ تم إضافة الرد: {keyword}")

async def remove_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_authorized(context.bot, update.effective_chat.id, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    if not context.args:
        return await update.message.reply_text("/remove_reply كلمة")
    keyword = context.args[0].lower()
    await db_execute("DELETE FROM replies WHERE keyword=?", keyword)
    await update.message.reply_text(f"✅ تم حذف الرد: {keyword}")

async def list_replies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    replies = await db_execute("SELECT * FROM replies")
    if not replies:
        return await update.message.reply_text("📭 لا توجد ردود")
    text = "💬 الردود:\n" + "\n".join(f"• {r['keyword']} → {r['reply'][:30]}..." for r in replies)
    await update.message.reply_text(text)

async def log_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    logs = await db_execute("SELECT * FROM mod_log WHERE chat_id=? ORDER BY id DESC LIMIT 20", cid)
    if not logs:
        return await update.message.reply_text("📭 لا توجد سجلات")
    text = "📜 السجل:\n"
    for log in logs:
        text += f"• {log['action']} → {log['target_id']} ({log['timestamp'][:16]})\n"
    await update.message.reply_text(text)

async def group_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    settings = await db_execute_one("SELECT * FROM group_security WHERE chat_id=?", cid)
    if not settings:
        settings = {"lock_links": 0, "lock_mentions": 0, "slow_mode_seconds": 0, 
                   "welcome_msg": "", "goodbye_msg": ""}
    text = f"⚙️ إعدادات المجموعة\n🔗 روابط: {'✅' if settings['lock_links'] else '❌'}\n"
    text += f"👥 منشنات: {'✅' if settings['lock_mentions'] else '❌'}\n"
    text += f"⏱️ بطء: {settings.get('slow_mode_seconds', 0)}ث\n"
    text += f"📝 ترحيب: {settings.get('welcome_msg', '')[:30]}\n"
    text += f"👋 وداع: {settings.get('goodbye_msg', '')[:30]}"
    await update.message.reply_text(text)

async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER:
        return await update.message.reply_text(t(uid, "admin_only"))
    try:
        await reload_banned_words()
        await reload_replies()
        await update.message.reply_text(t(0, "reload_success"))
    except:
        await update.message.reply_text(t(0, "reload_fail"))

async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    start = time.time()
    msg = await update.message.reply_text("🫀 جاري الفحص...")
    ping = round((time.time() - start) * 1000)
    try:
        await db_execute_one("SELECT 1")
        db_status = "✅"
    except:
        db_status = "❌"
    await msg.edit_text(t(uid, "ping_status", ping=ping, db=db_status, 
                         time=datetime.now().strftime("%H:%M:%S")))

# ==================== لوحة التحكم /panel ====================
async def panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if not await is_authorized(context.bot, cid, uid):
        return await update.message.reply_text(t(uid, "admin_only"))
    if not update.message.reply_to_message:
        return await update.message.reply_text("📝 استخدم الأمر بالرد على الشخص")
    
    target = update.message.reply_to_message.from_user
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔇 كتم", callback_data=f"act_mute_{cid}_{target.id}"),
         InlineKeyboardButton("🔊 فك كتم", callback_data=f"act_unmute_{cid}_{target.id}")],
        [InlineKeyboardButton("🚫 حظر", callback_data=f"act_ban_{cid}_{target.id}"),
         InlineKeyboardButton("✅ فك حظر", callback_data=f"act_unban_{cid}_{target.id}")],
        [InlineKeyboardButton("👢 طرد", callback_data=f"act_kick_{cid}_{target.id}"),
         InlineKeyboardButton("⚠️ تحذير", callback_data=f"act_warn_{cid}_{target.id}")],
        [InlineKeyboardButton("⭐ ترقية", callback_data=f"act_promote_{cid}_{target.id}"),
         InlineKeyboardButton("⬇️ تنزيل", callback_data=f"act_demote_{cid}_{target.id}")],
        [InlineKeyboardButton("🗑️ حذف الرسالة", callback_data=f"act_del_{cid}_{update.message.reply_to_message.message_id}")],
        [InlineKeyboardButton(t(uid, "back"), callback_data="back")],
    ])
    await update.message.reply_text(f"⚙️ إجراء على {target.first_name}:", reply_markup=kb)

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER:
        return await update.message.reply_text(t(uid, "admin_only"))
    text = " ".join(context.args)
    if not text:
        return await update.message.reply_text("/broadcast نص")
    
    users = await db_execute("SELECT user_id FROM users WHERE banned=0")
    sent = 0
    for u in users:
        try:
            await context.bot.send_message(u["user_id"], text)
            sent += 1
            await asyncio.sleep(0.1)
        except:
            pass
    await update.message.reply_text(t(0, "broadcast_sent").format(count=sent))

# ==================== كولباكس الأزرار ====================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    data = query.data
    cid = update.effective_chat.id if update.effective_chat else None
    
    # === أزرار رئيسية ===
    if data == "back":
        await query.edit_message_text(t(uid, "welcome", bot=BOT_NAME), reply_markup=main_keyboard(uid))
    
    elif data == "add_ch":
        context.user_data["state"] = "ADD_CH"
        await query.edit_message_text(t(uid, "send_channel_id"))
    
    elif data == "my_ch":
        channels = await db_execute("SELECT * FROM channels WHERE user_id=?", uid)
        if not channels:
            return await query.edit_message_text(t(uid, "no_channels"), reply_markup=main_keyboard(uid))
        kb = []
        for ch in channels:
            kb.append([InlineKeyboardButton(f"📢 {ch['channel_name'] or ch['channel_id']}", 
                                            callback_data=f"sel_ch_{ch['id']}")])
            kb.append([InlineKeyboardButton("🗑️ حذف", callback_data=f"del_ch_{ch['id']}")])
        kb.append([InlineKeyboardButton(t(uid, "back"), callback_data="back")])
        await query.edit_message_text("📡 قنواتي:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("sel_ch_"):
        ch_id = int(data.split("_")[2])
        await db_execute("UPDATE users SET active_channel=? WHERE user_id=?", ch_id, uid)
        await query.edit_message_text("✅ تم التفعيل", reply_markup=main_keyboard(uid))
    
    elif data.startswith("del_ch_"):
        ch_id = int(data.split("_")[2])
        await db_execute("DELETE FROM channels WHERE id=? AND user_id=?", ch_id, uid)
        await db_execute("DELETE FROM posts WHERE channel_db_id=?", ch_id)
        await query.edit_message_text(t(uid, "channel_deleted"), reply_markup=main_keyboard(uid))
    
    elif data == "add_posts":
        ch = await db_execute_one("SELECT id FROM channels WHERE user_id=? AND active_channel=id LIMIT 1", uid)
        if not ch:
            return await query.edit_message_text(t(uid, "no_channels"))
        context.user_data["state"] = "ADD_POSTS"
        context.user_data["posts"] = []
        await query.edit_message_text("📥 أرسل 15 منشوراً (/cancel للإلغاء)")
    
    elif data == "publish_one":
        ch = await db_execute_one("SELECT id,channel_id FROM channels WHERE user_id=? AND active_channel=id LIMIT 1", uid)
        if not ch:
            return await query.edit_message_text(t(uid, "no_channels"))
        post = await db_execute_one("SELECT * FROM posts WHERE channel_db_id=? AND published=0 ORDER BY id LIMIT 1", ch["id"])
        if not post:
            return await query.edit_message_text(t(uid, "no_posts"))
        try:
            if post["media_type"] == "photo":
                await context.bot.send_photo(ch["channel_id"], post["media_file_id"], caption=post["text"])
            elif post["media_type"] == "video":
                await context.bot.send_video(ch["channel_id"], post["media_file_id"], caption=post["text"])
            else:
                await context.bot.send_message(ch["channel_id"], post["text"])
            await db_execute("UPDATE posts SET published=1 WHERE id=?", post["id"])
            await add_points(uid, 5)
            await query.edit_message_text(t(uid, "post_published"), reply_markup=main_keyboard(uid))
        except Exception as e:
            await query.edit_message_text(f"❌ {e}")
    
    elif data == "my_posts":
        ch = await db_execute_one("SELECT id FROM channels WHERE user_id=? AND active_channel=id LIMIT 1", uid)
        if not ch:
            return await query.edit_message_text(t(uid, "no_channels"))
        posts = await db_execute("SELECT * FROM posts WHERE channel_db_id=? AND published=0 ORDER BY id LIMIT 15", ch["id"])
        if not posts:
            return await query.edit_message_text(t(uid, "no_posts"))
        text = "📋 منشوراتي:\n"
        kb = []
        for p in posts:
            text += f"• {p['text'][:30] if p['text'] else '🖼️'}...\n"
            kb.append([InlineKeyboardButton(f"🗑️ حذف #{p['id']}", callback_data=f"del_post_{p['id']}")])
        kb.append([InlineKeyboardButton("🗑️ حذف الكل", callback_data="del_all_posts")])
        kb.append([InlineKeyboardButton(t(uid, "back"), callback_data="back")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("del_post_"):
        pid = int(data.split("_")[2])
        await db_execute("DELETE FROM posts WHERE id=?", pid)
        await query.edit_message_text("✅ تم الحذف", reply_markup=main_keyboard(uid))
    
    elif data == "del_all_posts":
        ch = await db_execute_one("SELECT id FROM channels WHERE user_id=? AND active_channel=id LIMIT 1", uid)
        if ch:
            await db_execute("DELETE FROM posts WHERE channel_db_id=?", ch["id"])
            await query.edit_message_text("✅ تم حذف الكل", reply_markup=main_keyboard(uid))
    
    elif data == "recycle":
        ch = await db_execute_one("SELECT id FROM channels WHERE user_id=? AND active_channel=id LIMIT 1", uid)
        if ch:
            await db_execute("UPDATE posts SET published=0 WHERE channel_db_id=?", ch["id"])
            await query.edit_message_text(t(uid, "posts_recycled"), reply_markup=main_keyboard(uid))
    
    elif data == "publish_all":
        ch = await db_execute_one("SELECT id,channel_id FROM channels WHERE user_id=? AND active_channel=id LIMIT 1", uid)
        if not ch:
            return await query.edit_message_text(t(uid, "no_channels"))
        posts = await db_execute("SELECT * FROM posts WHERE channel_db_id=? AND published=0", ch["id"])
        if not posts:
            return await query.edit_message_text(t(uid, "no_posts"))
        count = 0
        for p in posts:
            try:
                if p["media_type"] == "photo":
                    await context.bot.send_photo(ch["channel_id"], p["media_file_id"], caption=p["text"])
                elif p["media_type"] == "video":
                    await context.bot.send_video(ch["channel_id"], p["media_file_id"], caption=p["text"])
                else:
                    await context.bot.send_message(ch["channel_id"], p["text"])
                await db_execute("UPDATE posts SET published=1 WHERE id=?", p["id"])
                count += 1
                await asyncio.sleep(1)
            except:
                pass
        await query.edit_message_text(t(uid, "all_posts_published").format(count=count), reply_markup=main_keyboard(uid))
    
    elif data == "stats":
        chs = await db_execute("SELECT COUNT(*) as c FROM channels WHERE user_id=?", uid)
        ps = await db_execute("SELECT COUNT(*) as c FROM posts WHERE channel_db_id IN (SELECT id FROM channels WHERE user_id=?)", uid)
        await query.edit_message_text(f"📊 قنوات: {chs[0]['c'] if chs else 0}\n📝 منشورات: {ps[0]['c'] if ps else 0}")
    
    elif data == "full_stats":
        chs = await db_execute("SELECT id, channel_name FROM channels WHERE user_id=?", uid)
        if not chs:
            return await query.edit_message_text(t(uid, "no_channels"))
        text = "📈 ملخص القنوات:\n"
        for ch in chs:
            unpub = await db_execute_one("SELECT COUNT(*) as c FROM posts WHERE channel_db_id=? AND published=0", ch["id"])
            text += f"• {ch['channel_name']}: {unpub['c'] if unpub else 0} غير منشور\n"
        await query.edit_message_text(text)
    
    elif data == "ch_stats":
        ch = await db_execute_one("SELECT id,channel_name FROM channels WHERE user_id=? AND active_channel=id LIMIT 1", uid)
        if not ch:
            return await query.edit_message_text(t(uid, "no_channels"))
        total = await db_execute_one("SELECT COUNT(*) as c FROM posts WHERE channel_db_id=?", ch["id"])
        pub = await db_execute_one("SELECT COUNT(*) as c FROM posts WHERE channel_db_id=? AND published=1", ch["id"])
        unpub = await db_execute_one("SELECT COUNT(*) as c FROM posts WHERE channel_db_id=? AND published=0", ch["id"])
        text = f"📊 {ch['channel_name']}\n📝 الكل: {total['c'] if total else 0}\n✅ منشور: {pub['c'] if pub else 0}\n⏳ غير منشور: {unpub['c'] if unpub else 0}"
        await query.edit_message_text(text)
    
    elif data == "my_groups":
        groups = await db_execute("SELECT * FROM groups WHERE added_by=?", uid)
        if not groups:
            return await query.edit_message_text("📭 لا توجد مجموعات", reply_markup=main_keyboard(uid))
        kb = []
        for g in groups:
            kb.append([InlineKeyboardButton(f"📌 {g['chat_name']}", callback_data=f"gset_{g['chat_id']}")])
        kb.append([InlineKeyboardButton(t(uid, "back"), callback_data="back")])
        await query.edit_message_text("👥 مجموعاتي:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("gset_"):
        try:
            cid = int(data.split("_")[1])
        except:
            return
        settings = await db_execute_one("SELECT * FROM group_security WHERE chat_id=?", cid) or {}
        kb = group_settings_keyboard(cid, settings)
        await query.edit_message_text(f"⚙️ إعدادات المجموعة {cid}:", reply_markup=kb)
    
    # === إعدادات المجموعة ===
    elif data.startswith("gset_links_"):
        parts = data.split("_")
        cid = int(parts[2])
        val = int(parts[3])
        await db_execute("INSERT OR IGNORE INTO group_security(chat_id) VALUES(?)", cid)
        await db_execute("UPDATE group_security SET lock_links=? WHERE chat_id=?", val, cid)
        await query.answer(f"{'✅ مفعل' if val else '❌ معطل'}")
        settings = await db_execute_one("SELECT * FROM group_security WHERE chat_id=?", cid) or {}
        await query.edit_message_reply_markup(reply_markup=group_settings_keyboard(cid, settings))
    
    elif data.startswith("gset_mentions_"):
        parts = data.split("_")
        cid = int(parts[2])
        val = int(parts[3])
        await db_execute("INSERT OR IGNORE INTO group_security(chat_id) VALUES(?)", cid)
        await db_execute("UPDATE group_security SET lock_mentions=? WHERE chat_id=?", val, cid)
        await query.answer(f"{'✅ مفعل' if val else '❌ معطل'}")
        settings = await db_execute_one("SELECT * FROM group_security WHERE chat_id=?", cid) or {}
        await query.edit_message_reply_markup(reply_markup=group_settings_keyboard(cid, settings))
    
    elif data.startswith("gset_slow_"):
        cid = int(data.split("_")[2])
        context.user_data["state"] = f"SET_SLOW_{cid}"
        await query.edit_message_text(t(uid, "send_seconds"))
    
    elif data.startswith("gset_welcome_"):
        cid = int(data.split("_")[2])
        context.user_data["state"] = f"SET_WELCOME_{cid}"
        await query.edit_message_text("📝 أرسل رسالة الترحيب (استخدم {user} و {chat})")
    
    elif data.startswith("gset_goodbye_"):
        cid = int(data.split("_")[2])
        context.user_data["state"] = f"SET_GOODBYE_{cid}"
        await query.edit_message_text("👋 أرسل رسالة الوداع")
    
    elif data.startswith("gset_banned_"):
        cid = int(data.split("_")[2])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة كلمة", callback_data=f"bw_add_{cid}"),
             InlineKeyboardButton("🗑️ حذف كلمة", callback_data=f"bw_del_{cid}")],
            [InlineKeyboardButton("📋 عرض الكلمات", callback_data=f"bw_list_{cid}"),
             InlineKeyboardButton(t(uid, "back"), callback_data=f"gset_{cid}")],
        ])
        await query.edit_message_text("🚫 إدارة الكلمات المحظورة", reply_markup=kb)
    
    elif data.startswith("gset_replies_"):
        cid = int(data.split("_")[2])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة رد", callback_data=f"rep_add_{cid}"),
             InlineKeyboardButton("🗑️ حذف رد", callback_data=f"rep_del_{cid}")],
            [InlineKeyboardButton("📋 عرض الردود", callback_data=f"rep_list_{cid}"),
             InlineKeyboardButton(t(uid, "back"), callback_data=f"gset_{cid}")],
        ])
        await query.edit_message_text("💬 إدارة الردود", reply_markup=kb)
    
    elif data.startswith("gset_log_"):
        cid = int(data.split("_")[2])
        logs = await db_execute("SELECT * FROM mod_log WHERE chat_id=? ORDER BY id DESC LIMIT 20", cid)
        text = "📜 آخر 20 إجراء:\n" + "\n".join(f"• {l['action']} → {l['target_id']}" for l in logs) if logs else "لا يوجد سجل"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(uid, "back"), callback_data=f"gset_{cid}")]
        ]))
    
    elif data.startswith("gset_penalty_"):
        cid = int(data.split("_")[2])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 طرد تلقائي", callback_data=f"penalty_kick_{cid}"),
             InlineKeyboardButton("🛑 حظر تلقائي", callback_data=f"penalty_ban_{cid}")],
            [InlineKeyboardButton("🔇 كتم تلقائي", callback_data=f"penalty_mute_{cid}"),
             InlineKeyboardButton("⚖️ لا شيء", callback_data=f"penalty_none_{cid}")],
            [InlineKeyboardButton(t(uid, "back"), callback_data=f"gset_{cid}")],
        ])
        await query.edit_message_text("⚖️ اختيار العقوبة التلقائية", reply_markup=kb)
    
    # === كلمات محظورة ===
    elif data.startswith("bw_add_"):
        cid = int(data.split("_")[2])
        context.user_data["state"] = f"ADD_BW_{cid}"
        await query.edit_message_text("🚫 أرسل الكلمة المراد حظرها:")
    
    elif data.startswith("bw_del_"):
        cid = int(data.split("_")[2])
        context.user_data["state"] = f"DEL_BW_{cid}"
        await query.edit_message_text("🗑️ أرسل الكلمة لإزالتها:")
    
    elif data.startswith("bw_list_"):
        cid = int(data.split("_")[2])
        words = await db_execute("SELECT word FROM banned_words WHERE chat_id=? OR chat_id=-1", cid)
        text = "🚫 الكلمات المحظورة:\n" + ", ".join(w["word"] for w in words) if words else "لا يوجد"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(uid, "back"), callback_data=f"gset_banned_{cid}")]
        ]))
    
    # === ردود ===
    elif data.startswith("rep_add_"):
        cid = int(data.split("_")[2])
        context.user_data["state"] = f"ADD_REP_KW_{cid}"
        await query.edit_message_text("📝 أرسل الكلمة:")
    
    elif data.startswith("rep_del_"):
        cid = int(data.split("_")[2])
        context.user_data["state"] = f"DEL_REP_{cid}"
        await query.edit_message_text("🗑️ أرسل الكلمة المراد حذف ردها:")
    
    elif data.startswith("rep_list_"):
        cid = int(data.split("_")[2])
        replies = await db_execute("SELECT keyword, reply FROM replies")
        text = "💬 الردود:\n" + "\n".join(f"• {r['keyword']} → {r['reply'][:30]}" for r in replies) if replies else "لا يوجد"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(uid, "back"), callback_data=f"gset_replies_{cid}")]
        ]))
    
    # === عقوبات ===
    elif data.startswith("penalty_"):
        parts = data.split("_")
        action = parts[1]
        cid = int(parts[2])
        await db_execute("INSERT OR IGNORE INTO group_security(chat_id) VALUES(?)", cid)
        await db_execute("UPDATE group_security SET auto_penalty=? WHERE chat_id=?", action, cid)
        await query.answer(f"✅ تم تعيين العقوبة: {action}")
        settings = await db_execute_one("SELECT * FROM group_security WHERE chat_id=?", cid) or {}
        await query.edit_message_reply_markup(reply_markup=group_settings_keyboard(cid, settings))
    
    # === إجراءات لوحة التحكم ===
    elif data.startswith("act_mute_"):
        parts = data.split("_")
        cid = int(parts[2])
        tid = int(parts[3])
        if not await is_authorized(context.bot, cid, uid):
            return await query.answer("🔒 لا صلاحية", show_alert=True)
        try:
            await context.bot.restrict_chat_member(cid, tid, ChatPermissions(can_send_messages=False))
            await query.edit_message_text(f"✅ تم كتم {tid}")
        except Exception as e:
            await query.answer(f"❌ {e}", show_alert=True)
    
    elif data.startswith("act_unmute_"):
        parts = data.split("_")
        cid = int(parts[2])
        tid = int(parts[3])
        if not await is_authorized(context.bot, cid, uid):
            return await query.answer("🔒 لا صلاحية", show_alert=True)
        try:
            perms = ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True)
            await context.bot.restrict_chat_member(cid, tid, perms)
            await query.edit_message_text(f"✅ فك كتم {tid}")
        except Exception as e:
            await query.answer(f"❌ {e}", show_alert=True)
    
    elif data.startswith("act_ban_"):
        parts = data.split("_")
        cid = int(parts[2])
        tid = int(parts[3])
        if not await is_authorized(context.bot, cid, uid):
            return await query.answer("🔒 لا صلاحية", show_alert=True)
        try:
            await context.bot.ban_chat_member(cid, tid)
            await query.edit_message_text(f"✅ حظر {tid}")
        except Exception as e:
            await query.answer(f"❌ {e}", show_alert=True)
    
    elif data.startswith("act_unban_"):
        parts = data.split("_")
        cid = int(parts[2])
        tid = int(parts[3])
        if not await is_authorized(context.bot, cid, uid):
            return await query.answer("🔒 لا صلاحية", show_alert=True)
        try:
            await context.bot.unban_chat_member(cid, tid)
            await query.edit_message_text(f"✅ فك حظر {tid}")
        except Exception as e:
            await query.answer(f"❌ {e}", show_alert=True)
    
    elif data.startswith("act_kick_"):
        parts = data.split("_")
        cid = int(parts[2])
        tid = int(parts[3])
        if not await is_authorized(context.bot, cid, uid):
            return await query.answer("🔒 لا صلاحية", show_alert=True)
        try:
            await context.bot.ban_chat_member(cid, tid)
            await context.bot.unban_chat_member(cid, tid)
            await query.edit_message_text(f"✅ طرد {tid}")
        except Exception as e:
            await query.answer(f"❌ {e}", show_alert=True)
    
    elif data.startswith("act_warn_"):
        parts = data.split("_")
        cid = int(parts[2])
        tid = int(parts[3])
        if not await is_authorized(context.bot, cid, uid):
            return await query.answer("🔒 لا صلاحية", show_alert=True)
        await db_execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", tid)
        await db_execute("INSERT OR IGNORE INTO user_warnings(user_id,chat_id,warnings) VALUES(?,?,0)", tid, cid)
        await db_execute("UPDATE user_warnings SET warnings=warnings+1 WHERE user_id=? AND chat_id=?", tid, cid)
        row = await db_execute_one("SELECT warnings FROM user_warnings WHERE user_id=? AND chat_id=?", tid, cid)
        warns = row["warnings"] if row else 0
        if warns >= 3:
            try:
                await context.bot.ban_chat_member(cid, tid)
                await query.edit_message_text(f"🚫 حظر تلقائي {tid} (3 تحذيرات)")
            except:
                await query.edit_message_text(f"⚠️ 3 تحذيرات لـ {tid}")
        else:
            await query.edit_message_text(f"⚠️ تحذير {tid} ({warns}/3)")
    
    elif data.startswith("act_promote_"):
        parts = data.split("_")
        cid = int(parts[2])
        tid = int(parts[3])
        if not await is_authorized(context.bot, cid, uid):
            return await query.answer("🔒 لا صلاحية", show_alert=True)
        try:
            await context.bot.promote_chat_member(cid, tid, can_manage_chat=True, can_delete_messages=True, can_restrict_members=True, can_promote_members=True, can_change_info=True, can_invite_users=True, can_pin_messages=True)
            await query.edit_message_text(f"⭐ تم ترقية {tid}")
        except Exception as e:
            await query.answer(f"❌ {e}", show_alert=True)
    
    elif data.startswith("act_demote_"):
        parts = data.split("_")
        cid = int(parts[2])
        tid = int(parts[3])
        if not await is_authorized(context.bot, cid, uid):
            return await query.answer("🔒 لا صلاحية", show_alert=True)
        try:
            await context.bot.promote_chat_member(cid, tid, can_manage_chat=False, can_delete_messages=False, can_restrict_members=False, can_promote_members=False, can_change_info=False, can_invite_users=False, can_pin_messages=False)
            await query.edit_message_text(f"⬇️ تم تنزيل {tid}")
        except Exception as e:
            await query.answer(f"❌ {e}", show_alert=True)
    
    elif data.startswith("act_del_"):
        parts = data.split("_")
        cid = int(parts[2])
        mid = int(parts[3])
        if not await is_authorized(context.bot, cid, uid):
            return await query.answer("🔒 لا صلاحية", show_alert=True)
        try:
            await context.bot.delete_message(cid, mid)
            await query.edit_message_text("✅ تم حذف الرسالة")
        except Exception as e:
            await query.answer(f"❌ {e}", show_alert=True)
    
    # === المسابقات ===
    elif data == "contests":
        contests = await db_execute("SELECT * FROM contests WHERE status='active' AND end_date > ?", datetime.now().isoformat())
        if not contests:
            return await query.edit_message_text(t(uid, "no_contests"), reply_markup=main_keyboard(uid))
        kb = []
        for c in contests:
            kb.append([InlineKeyboardButton(f"📌 {c['title']} - {c['prize']}", callback_data=f"join_{c['id']}")])
        kb.append([InlineKeyboardButton("🏆 الفائزين", callback_data="winners")])
        kb.append([InlineKeyboardButton(t(uid, "back"), callback_data="back")])
        await query.edit_message_text(t(uid, "contests_active"), reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("join_"):
        contest_id = int(data.split("_")[1])
        try:
            await db_execute("INSERT INTO contest_parts(contest_id,user_id,joined_at) VALUES(?,?,?)", 
                           contest_id, uid, datetime.now().isoformat())
            await add_points(uid, 5)
            await query.edit_message_text(t(uid, "contest_joined"), reply_markup=main_keyboard(uid))
        except:
            await query.edit_message_text(t(uid, "contest_already"), reply_markup=main_keyboard(uid))
    
    elif data == "winners":
        winners = await db_execute("SELECT c.title, cw.winner_id FROM contest_winners cw JOIN contests c ON cw.contest_id=c.id ORDER BY cw.rowid DESC LIMIT 10")
        if not winners:
            return await query.edit_message_text(t(uid, "no_winners"))
        text = "🏆 الفائزون:\n"
        for w in winners:
            text += f"• {w['title']} → {w['winner_id']}\n"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(uid, "back"), callback_data="contests")]
        ]))
    
    # === إحالات ===
    elif data == "referral":
        code = (await db_execute_one("SELECT referral_code FROM users WHERE user_id=?", uid)) or {}
        if not code.get("referral_code"):
            code = hashlib.md5(f"{uid}{time.time()}".encode()).hexdigest()[:8]
            await db_execute("UPDATE users SET referral_code=? WHERE user_id=?", code, uid)
        else:
            code = code["referral_code"]
        reward = await db_execute_one("SELECT total_reward_days, claimed_reward_days FROM referral_rewards WHERE user_id=?", uid)
        total = reward["total_reward_days"] if reward else 0
        claimed = reward["claimed_reward_days"] if reward else 0
        count = await db_execute_one("SELECT COUNT(*) as c FROM referrals WHERE ref_id=?", uid)
        link = f"https://t.me/{BOT_USERNAME}?start=ref_{code}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 نسخ الرابط", callback_data=f"copy_{code}")],
            [InlineKeyboardButton("🎁 صرف المكافآت", callback_data="claim_reward")],
            [InlineKeyboardButton("👥 المحالين", callback_data="ref_list")],
            [InlineKeyboardButton(t(uid, "back"), callback_data="back")],
        ])
        text = t(uid, "referral_link", link=link, count=count["c"] if count else 0, rewards=total-claimed)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="MarkdownV2")
    
    elif data.startswith("copy_"):
        code = data.split("_")[1]
        await query.answer(f"https://t.me/{BOT_USERNAME}?start=ref_{code}", show_alert=True)
    
    elif data == "claim_reward":
        reward = await db_execute_one("SELECT total_reward_days, claimed_reward_days FROM referral_rewards WHERE user_id=?", uid)
        if not reward or reward["total_reward_days"] <= reward["claimed_reward_days"]:
            return await query.answer(t(uid, "no_reward"), show_alert=True)
        avail = reward["total_reward_days"] - reward["claimed_reward_days"]
        await db_execute("UPDATE referral_rewards SET claimed_reward_days=claimed_reward_days+? WHERE user_id=?", avail, uid)
        # إضافة أيام اشتراك
        current = await get_subscription_days_left(uid)
        new_days = current + avail
        end_date = (datetime.now() + timedelta(days=new_days)).isoformat()
        await db_execute("UPDATE users SET subscription_end=? WHERE user_id=?", enc(end_date), uid)
        await query.edit_message_text(t(uid, "reward_claimed").format(days=avail), reply_markup=main_keyboard(uid))
    
    elif data == "ref_list":
        refs = await db_execute("SELECT new_id FROM referrals WHERE ref_id=?", uid)
        text = "👥 المحالين:\n" + "\n".join(f"• {r['new_id']}" for r in refs) if refs else "لا يوجد"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(uid, "back"), callback_data="referral")]
        ]))
    
    # === تذكيرات ===
    elif data == "reminder":
        rem = await db_execute_one("SELECT * FROM reminders WHERE user_id=?", uid)
        if not rem:
            await db_execute("INSERT INTO reminders(user_id) VALUES(?)", uid)
            rem = await db_execute_one("SELECT * FROM reminders WHERE user_id=?", uid)
        sub = "✅" if rem["sub"] else "❌"
        daily = "✅" if rem["daily"] else "❌"
        weekly = "✅" if rem["weekly"] else "❌"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🔔 اشتراك: {sub}", callback_data="rem_sub"),
             InlineKeyboardButton(f"📊 يومي: {daily}", callback_data="rem_daily")],
            [InlineKeyboardButton(f"📈 أسبوعي: {weekly}", callback_data="rem_weekly"),
             InlineKeyboardButton(f"⏰ قبل {rem['days_before']} أيام", callback_data="rem_days")],
            [InlineKeyboardButton(t(uid, "back"), callback_data="back")],
        ])
        await query.edit_message_text(t(uid, "reminder_settings", sub=sub, daily=daily, weekly=weekly, days=rem['days_before']), reply_markup=kb)
    
    elif data == "rem_sub":
        rem = await db_execute_one("SELECT sub FROM reminders WHERE user_id=?", uid)
        new_val = 0 if rem["sub"] else 1
        await db_execute("UPDATE reminders SET sub=? WHERE user_id=?", new_val, uid)
        await query.answer(f"{'✅ مفعل' if new_val else '❌ معطل'}")
    
    elif data == "rem_daily":
        rem = await db_execute_one("SELECT daily FROM reminders WHERE user_id=?", uid)
        new_val = 0 if rem["daily"] else 1
        await db_execute("UPDATE reminders SET daily=? WHERE user_id=?", new_val, uid)
        await query.answer(f"{'✅ مفعل' if new_val else '❌ معطل'}")
    
    elif data == "rem_weekly":
        rem = await db_execute_one("SELECT weekly FROM reminders WHERE user_id=?", uid)
        new_val = 0 if rem["weekly"] else 1
        await db_execute("UPDATE reminders SET weekly=? WHERE user_id=?", new_val, uid)
        await query.answer(f"{'✅ مفعل' if new_val else '❌ معطل'}")
    
    elif data == "rem_days":
        context.user_data["state"] = "SET_REM_DAYS"
        await query.edit_message_text("⏰ أرسل عدد الأيام قبل انتهاء الاشتراك (1-30):")
    
    # === ترجمة ===
    elif data == "translation":
        lang = await db_execute_one("SELECT lang FROM user_translation WHERE user_id=?", uid)
        current = lang["lang"] if lang else "off"
        status = t(uid, "translation_on", lang=current) if current != "off" else t(uid, "translation_off")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("العربية", callback_data="trans_ar"),
             InlineKeyboardButton("English", callback_data="trans_en")],
            [InlineKeyboardButton("Français", callback_data="trans_fr"),
             InlineKeyboardButton("Türkçe", callback_data="trans_tr")],
            [InlineKeyboardButton("Русский", callback_data="trans_ru"),
             InlineKeyboardButton("Deutsch", callback_data="trans_de")],
            [InlineKeyboardButton("Español", callback_data="trans_es"),
             InlineKeyboardButton("Português", callback_data="trans_pt")],
            [InlineKeyboardButton(t(uid, "translation_off"), callback_data="trans_off"),
             InlineKeyboardButton(t(uid, "back"), callback_data="back")],
        ])
        await query.edit_message_text(f"{status}\n\n{t(uid, 'translation_choose')}", reply_markup=kb)
    
    elif data.startswith("trans_"):
        lang = data.split("_")[1]
        if lang == "off":
            await db_execute("DELETE FROM user_translation WHERE user_id=?", uid)
            await query.edit_message_text(t(uid, "translation_disabled"), reply_markup=main_keyboard(uid))
        else:
            await db_execute("INSERT OR REPLACE INTO user_translation(user_id,lang) VALUES(?,?)", uid, lang)
            await query.edit_message_text(t(uid, "translation_enabled", lang=lang), reply_markup=main_keyboard(uid))
    
    # === دعم ===
    elif data == "support":
        context.user_data["state"] = "SUPPORT"
        await query.edit_message_text(t(uid, "support_welcome"))
    
    # === مطور ===
    elif data == "developer":
        await query.edit_message_text("👨‍💻 المطور: @RelaxMgr\n📌 الإصدار: 20.0.3\n🚀 جميع الحقوق محفوظة")
    
    # === تحديثات ===
    elif data == "updates":
        await query.edit_message_text("📢 قناة التحديثات:\nhttps://t.me/RelaxUpdates")
    
    # === مساعدة ===
    elif data == "help":
        await help_command(update, context)
    
    # === لغة ===
    elif data == "language":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("العربية 🇸🇦", callback_data="lang_ar"),
             InlineKeyboardButton("English 🇬🇧", callback_data="lang_en")],
            [InlineKeyboardButton("Français 🇫🇷", callback_data="lang_fr"),
             InlineKeyboardButton("Türkçe 🇹🇷", callback_data="lang_tr")],
            [InlineKeyboardButton("Русский 🇷🇺", callback_data="lang_ru"),
             InlineKeyboardButton("Deutsch 🇩🇪", callback_data="lang_de")],
            [InlineKeyboardButton(t(uid, "back"), callback_data="back")],
        ])
        await query.edit_message_text(t(uid, "language"), reply_markup=kb)
    
    elif data.startswith("lang_"):
        lang = data.split("_")[1]
        await set_user_lang(uid, lang)
        await query.edit_message_text(f"✅ تم تغيير اللغة إلى {lang}", reply_markup=main_keyboard(uid))
    
    # === رتبة ===
    elif data == "rank":
        row = await db_execute_one("SELECT points, level FROM users WHERE user_id=?", uid)
        if row:
            await query.edit_message_text(f"🏆 رتبتك\n⭐ المستوى: {row['level']}\n📊 النقاط: {row['points']}")
        else:
            await query.edit_message_text("🏆 لا توجد بيانات")
    
    # === أفضل 10 ===
    elif data == "top":
        tops = await db_execute("SELECT user_id, points, level FROM users ORDER BY points DESC LIMIT 10")
        if not tops:
            return await query.edit_message_text("📭 لا يوجد")
        text = "🏆 أفضل 10:\n"
        for i, u in enumerate(tops, 1):
            text += f"{i}. {u['user_id']} | Lv{u['level']} | {u['points']} نقطة\n"
        await query.edit_message_text(text)
    
    # === جدولة ===
    elif data == "schedule":
        context.user_data["state"] = "SCHEDULE"
        await query.edit_message_text("📝 أرسل التاريخ والوقت (YYYY-MM-DD HH:MM) ثم النص:")
    
    # === تجربة مجانية ===
    elif data == "trial":
        row = await db_execute_one("SELECT trial_used FROM users WHERE user_id=?", uid)
        if row and row["trial_used"]:
            return await query.answer(t(uid, "trial_used"), show_alert=True)
        if await has_active_subscription(uid):
            return await query.answer(t(uid, "already_subscribed"), show_alert=True)
        end_date = (datetime.now() + timedelta(days=30)).isoformat()
        await db_execute("UPDATE users SET trial_used=1, subscription_end=? WHERE user_id=?", enc(end_date), uid)
        await query.edit_message_text(t(uid, "trial_activated"), reply_markup=main_keyboard(uid))
    
    # === اشتراك ===
    elif data == "subscribe":
        if await has_active_subscription(uid):
            days = await get_subscription_days_left(uid)
            return await query.edit_message_text(f"✅ لديك اشتراك فعال، متبقي {days} يوم", reply_markup=main_keyboard(uid))
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐ 1 يوم - 5 نجوم", callback_data="buy_1_5"),
             InlineKeyboardButton("⭐ 2 يوم - 9 نجوم", callback_data="buy_2_9")],
            [InlineKeyboardButton("⭐ 30 يوم - 50 نجمة", callback_data="buy_30_50"),
             InlineKeyboardButton("⭐ 90 يوم - 120 نجمة", callback_data="buy_90_120")],
            [InlineKeyboardButton(t(uid, "back"), callback_data="back")],
        ])
        await query.edit_message_text("💎 اختر الباقة:", reply_markup=kb)
    
    elif data.startswith("buy_"):
        parts = data.split("_")
        days = int(parts[1])
        stars = int(parts[2])
        try:
            await context.bot.send_invoice(
                chat_id=uid,
                title=f"اشتراك {days} يوم",
                description=f"باقة {days} يوم مقابل {stars} نجمة",
                payload=f"sub_{days}_{stars}",
                currency="XTR",
                prices=[LabeledPrice(f"{days} يوم", stars)],
                start_parameter="subscribe"
            )
            await query.edit_message_text("📩 تم إرسال فاتورة الدفع")
        except Exception as e:
            await query.edit_message_text(f"❌ {e}")
    
    # === إعدادات ===
    elif data == "settings":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 النشر التلقائي", callback_data="toggle_auto")],
            [InlineKeyboardButton("♻️ إعادة التدوير", callback_data="toggle_recycle")],
            [InlineKeyboardButton(t(uid, "back"), callback_data="back")],
        ])
        await query.edit_message_text(t(uid, "settings"), reply_markup=kb)
    
    elif data == "toggle_auto":
        row = await db_execute_one("SELECT auto_publish FROM users WHERE user_id=?", uid)
        new_val = 0 if row["auto_publish"] else 1
        await db_execute("UPDATE users SET auto_publish=? WHERE user_id=?", new_val, uid)
        await query.edit_message_text(f"{'✅ مفعل' if new_val else '❌ معطل'}", reply_markup=main_keyboard(uid))
    
    elif data == "toggle_recycle":
        row = await db_execute_one("SELECT auto_recycle FROM users WHERE user_id=?", uid)
        new_val = 0 if row["auto_recycle"] else 1
        await db_execute("UPDATE users SET auto_recycle=? WHERE user_id=?", new_val, uid)
        await query.edit_message_text(f"♻️ إعادة التدوير: {'✅ مفعل' if new_val else '❌ معطل'}", reply_markup=main_keyboard(uid))
    
    # === لوحة الأدمن ===
    elif data == "admin_panel":
        if uid != OWNER:
            return await query.answer("🔒 للمطور فقط", show_alert=True)
        await query.edit_message_text("👑 لوحة الأدمن", reply_markup=admin_keyboard(uid))
    
    elif data == "adm_users":
        users = await db_execute("SELECT user_id, banned FROM users LIMIT 50")
        text = "👥 المستخدمين:\n" + "\n".join(f"{'🚫' if u['banned'] else '✅'} {u['user_id']}" for u in users) if users else "لا يوجد"
        await query.edit_message_text(text, reply_markup=admin_keyboard(uid))
    
    elif data == "adm_banned":
        users = await db_execute("SELECT user_id FROM users WHERE banned=1 LIMIT 50")
        text = "🚫 المحظورين:\n" + "\n".join(f"• {u['user_id']}" for u in users) if users else "لا يوجد"
        await query.edit_message_text(text, reply_markup=admin_keyboard(uid))
    
    elif data == "adm_channels":
        chs = await db_execute("SELECT channel_name FROM channels LIMIT 50")
        text = "📡 القنوات:\n" + "\n".join(f"• {c['channel_name']}" for c in chs) if chs else "لا يوجد"
        await query.edit_message_text(text, reply_markup=admin_keyboard(uid))
    
    elif data == "adm_groups":
        gs = await db_execute("SELECT chat_name FROM groups LIMIT 50")
        text = "📊 المجموعات:\n" + "\n".join(f"• {g['chat_name']}" for g in gs) if gs else "لا يوجد"
        await query.edit_message_text(text, reply_markup=admin_keyboard(uid))
    
    elif data == "adm_replies":
        reps = await db_execute("SELECT * FROM replies LIMIT 30")
        text = "💬 الردود:\n" + "\n".join(f"• {r['keyword']} → {r['reply'][:30]}" for r in reps) if reps else "لا يوجد"
        await query.edit_message_text(text, reply_markup=admin_keyboard(uid))
    
    elif data == "adm_tickets":
        tics = await db_execute("SELECT * FROM tickets ORDER BY num DESC LIMIT 10")
        text = "📋 التذاكر:\n" + "\n".join(f"#{t['num']} {t['username']} - {t['status']}" for t in tics) if tics else "لا يوجد"
        await query.edit_message_text(text, reply_markup=admin_keyboard(uid))
    
    elif data == "adm_contest":
        context.user_data["state"] = "CONTEST_TITLE"
        await query.edit_message_text("📝 عنوان المسابقة:")
    
    elif data == "declare_winner":
        context.user_data["state"] = "DECLARE_WINNER"
        await query.edit_message_text("📝 أرسل: contest_id user_id")
    
    elif data == "adm_broadcast":
        context.user_data["state"] = "BROADCAST"
        await query.edit_message_text("📨 أرسل نص الإذاعة:")
    
    elif data == "adm_backup":
        try:
            backup_file = DB_PATH.parent / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            shutil.copy2(DB_PATH, backup_file)
            await query.edit_message_text(t(uid, "backup_created"), reply_markup=admin_keyboard(uid))
        except Exception as e:
            await query.edit_message_text(f"❌ {e}")
    
    elif data == "adm_export":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 users", callback_data="export_users"),
             InlineKeyboardButton("📤 channels", callback_data="export_channels")],
            [InlineKeyboardButton("📤 posts", callback_data="export_posts"),
             InlineKeyboardButton("📤 groups", callback_data="export_groups")],
            [InlineKeyboardButton("📤 tickets", callback_data="export_tickets"),
             InlineKeyboardButton(t(uid, "back"), callback_data="admin_panel")],
        ])
        await query.edit_message_text("📥 اختر الجدول للتصدير:", reply_markup=kb)
    
    elif data.startswith("export_"):
        table = data.split("_")[1]
        rows = await db_execute(f"SELECT * FROM {table}")
        if not rows:
            return await query.edit_message_text("❌ لا توجد بيانات", reply_markup=admin_keyboard(uid))
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(rows[0].keys())
        for r in rows:
            writer.writerow(list(r.values()))
        f = io.BytesIO(output.getvalue().encode())
        f.name = f"{table}.csv"
        await context.bot.send_document(uid, f)
        await query.edit_message_text("✅ تم التصدير", reply_markup=admin_keyboard(uid))
    
    elif data == "ping_status":
        start = time.time()
        await query.answer()
        ping = round((time.time() - start) * 1000)
        try:
            await db_execute_one("SELECT 1")
            db_status = "✅"
        except:
            db_status = "❌"
        await query.edit_message_text(
            t(uid, "ping_status", ping=ping, db=db_status, time=datetime.now().strftime("%H:%M:%S")),
            reply_markup=admin_keyboard(uid)
        )
    
    elif data == "reload_files":
        if uid != OWNER:
            return await query.answer("🔒", show_alert=True)
        try:
            await reload_banned_words()
            await reload_replies()
            await query.edit_message_text(t(uid, "reload_success"), reply_markup=admin_keyboard(uid))
        except:
            await query.edit_message_text(t(uid, "reload_fail"), reply_markup=admin_keyboard(uid))
    
    else:
        await query.answer("❓ غير معروف")

# ==================== معالجات الدفع ====================
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    _, days, _ = payload.split("_")
    days = int(days)
    uid = update.effective_user.id
    current = await get_subscription_days_left(uid)
    new_days = current + days
    end_date = (datetime.now() + timedelta(days=new_days)).isoformat()
    await db_execute("UPDATE users SET subscription_end=? WHERE user_id=?", enc(end_date), uid)
    await update.message.reply_text(f"✅ تم تفعيل اشتراك {days} يوم! شكراً لك 💎")

# ==================== معالجات المجموعة ====================
async def auto_register_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            cid = update.effective_chat.id
            await db_execute("INSERT OR IGNORE INTO groups(chat_id,chat_name,added_by) VALUES(?,?,?)",
                           cid, update.effective_chat.title, update.effective_user.id)
            await db_execute("INSERT OR IGNORE INTO hidden_owners(chat_id,user_id) VALUES(?,?)",
                           cid, update.effective_user.id)
            try:
                await context.bot.send_message(update.effective_user.id, 
                    f"✅ تم إضافة البوت إلى {update.effective_chat.title}\n🔑 أنت المالك المخفي")
            except:
                pass

async def on_user_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return
    cid = update.effective_chat.id
    settings = await db_execute_one("SELECT welcome_msg FROM group_security WHERE chat_id=?", cid)
    if settings and settings["welcome_msg"]:
        for member in update.message.new_chat_members:
            if not member.is_bot:
                msg = settings["welcome_msg"].replace("{user}", member.first_name).replace("{chat}", update.effective_chat.title)
                try:
                    await update.message.reply_text(msg)
                except:
                    pass

async def on_user_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.left_chat_member:
        return
    cid = update.effective_chat.id
    settings = await db_execute_one("SELECT goodbye_msg FROM group_security WHERE chat_id=?", cid)
    if settings and settings["goodbye_msg"]:
        member = update.message.left_chat_member
        if not member.is_bot:
            msg = settings["goodbye_msg"].replace("{user}", member.first_name).replace("{chat}", update.effective_chat.title)
            try:
                await update.message.reply_text(msg)
            except:
                pass

# ==================== فلتر رسائل المجموعة ====================
async def group_message_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _bw_cache
    global _bw_cache
    if update.effective_chat.type not in ["group", "supergroup"]:
        return
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if update.effective_user.is_bot:
        return
    
    text = update.message.text or update.message.caption or ""
    
    # التحقق من الصلاحية للقفل
    settings = await db_execute_one("SELECT * FROM group_security WHERE chat_id=?", cid) or {}
    
    # حذف الروابط
    if settings.get("lock_links") and has_links(text):
        try:
            await update.message.delete()
            await db_execute("INSERT INTO mod_log(chat_id,admin_id,target_id,action,reason,timestamp) VALUES(?,?,?,?,?,?)",
                           cid, context.bot.id, uid, "auto_delete", "رابط", datetime.now().isoformat())
        except:
            pass
        return
    
    # حذف المنشنات
    if settings.get("lock_mentions") and has_mentions(text):
        try:
            await update.message.delete()
            await db_execute("INSERT INTO mod_log(chat_id,admin_id,target_id,action,reason,timestamp) VALUES(?,?,?,?,?,?)",
                           cid, context.bot.id, uid, "auto_delete", "منشن", datetime.now().isoformat())
        except:
            pass
        return
    
    global _bw_cache
    # الكلمات المحظورة
    global _bw_cache
    if not _bw_cache:
        _bw_cache = await load_banned_cache()
    words = _bw_cache.get(cid, []) + _bw_cache.get(-1, [])
    for word in words:
        if word in text.lower():
            try:
                await update.message.delete()
                await db_execute("INSERT INTO mod_log(chat_id,admin_id,target_id,action,reason,timestamp) VALUES(?,?,?,?,?,?)",
                               cid, context.bot.id, uid, "auto_delete", f"كلمة محظورة: {word}", datetime.now().isoformat())
            except:
                pass
            return
    
    # الردود التلقائية
    reply = await db_execute_one("SELECT reply FROM replies WHERE keyword=?", text.lower())
    if reply:
        try:
            await update.message.reply_text(reply["reply"])
        except:
            pass
        return
    
    # الردود السريعة المضمنة
    quick_replies = {
        "مرحباً": "أهلاً بك 🤍",
        "السلام عليكم": "وعليكم السلام 🌹",
        "شكراً": "العفو",
        "كيف حالك": "الحمد لله بخير 🙏",
        "صباح الخير": "صباح النور ☀️",
        "مساء الخير": "مساء النور 🌙",
        "مع السلامة": "مع السلامة 👋",
        "بالتوفيق": "الله يوفقك 🤲",
        "ماشاء الله": "تبارك الله 🌸",
        "الحمد لله": "الحمد لله دائماً 🌹",
    }
    for key, value in quick_replies.items():
        if key in text:
            try:
                await update.message.reply_text(value)
            except:
                pass
            break
    
    # الوضع البطيء
    slow = settings.get("slow_mode_seconds", 0)
    if slow > 0:
        last = await db_execute_one("SELECT message_time FROM user_messages WHERE user_id=? AND chat_id=?", uid, cid)
        now = datetime.now()
        if last:
            try:
                lt = datetime.fromisoformat(last["message_time"])
                if (now - lt).total_seconds() < slow:
                    try:
                        await update.message.delete()
                    except:
                        pass
                    return
            except:
                pass
        await db_execute("INSERT OR REPLACE INTO user_messages(user_id,chat_id,message_time) VALUES(?,?,?)",
                        uid, cid, now.isoformat())

# ==================== معالجات الرسائل الخاصة ====================
async def private_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text or ""
    state = context.user_data.get("state")
    
    if text == "/cancel":
        context.user_data.clear()
        await update.message.reply_text(t(uid, "cancelled"), reply_markup=main_keyboard(uid))
        return
    
    # === إضافة قناة ===
    if state == "ADD_CH":
        if not text.startswith("@") and not text.startswith("-100"):
            return await update.message.reply_text(t(uid, "send_channel_id"))
        try:
            ch = await context.bot.get_chat(text.strip())
            channel_id = str(ch.id)
            channel_name = ch.title or text.strip()
            await db_execute("INSERT INTO channels(user_id,channel_id,channel_name,created_at) VALUES(?,?,?,?)",
                           uid, channel_id, channel_name, datetime.now().isoformat())
            ch_id = (await db_execute_one("SELECT id FROM channels WHERE user_id=? ORDER BY id DESC LIMIT 1", uid))["id"]
            await db_execute("UPDATE users SET active_channel=? WHERE user_id=?", ch_id, uid)
            context.user_data.pop("state")
            await update.message.reply_text(t(uid, "channel_added", ch=channel_name), reply_markup=main_keyboard(uid))
        except Exception as e:
            await update.message.reply_text(f"❌ {e}")
    
    # === إضافة منشورات ===
    elif state == "ADD_POSTS":
        posts = context.user_data.get("posts", [])
        media_type = "text"
        media_file_id = None
        content = text
        
        if update.message.photo:
            media_type = "photo"
            media_file_id = update.message.photo[-1].file_id
            content = update.message.caption or ""
        elif update.message.video:
            media_type = "video"
            media_file_id = update.message.video.file_id
            content = update.message.caption or ""
        elif update.message.document:
            media_type = "document"
            media_file_id = update.message.document.file_id
            content = update.message.caption or ""
        elif update.message.audio:
            media_type = "audio"
            media_file_id = update.message.audio.file_id
            content = update.message.caption or ""
        elif update.message.voice:
            media_type = "voice"
            media_file_id = update.message.voice.file_id
            content = update.message.caption or ""
        elif update.message.animation:
            media_type = "animation"
            media_file_id = update.message.animation.file_id
            content = update.message.caption or ""
        
        posts.append((content, media_type, media_file_id))
        context.user_data["posts"] = posts
        
        if len(posts) >= 15:
            ch = await db_execute_one("SELECT id FROM channels WHERE user_id=? AND active_channel=id LIMIT 1", uid)
            if ch:
                for tx, mt, mf in posts:
                    await db_execute("INSERT INTO posts(channel_db_id,text,media_type,media_file_id,created_at) VALUES(?,?,?,?,?)",
                                   ch["id"], tx, mt, mf, datetime.now().isoformat())
            context.user_data.clear()
            await update.message.reply_text("✅ تم حفظ 15 منشوراً", reply_markup=main_keyboard(uid))
        else:
            await update.message.reply_text(f"📥 {len(posts)}/15")
    
    # === جدولة منشور ===
    elif state == "SCHEDULE":
        parts = text.split(maxsplit=2)
        if len(parts) >= 2:
            try:
                dt = datetime.strptime(f"{parts[0]} {parts[1]}", "%Y-%m-%d %H:%M")
                if dt > datetime.now():
                    ch = await db_execute_one("SELECT id,channel_id FROM channels WHERE user_id=? AND active_channel=id LIMIT 1", uid)
                    if ch:
                        task_data = parts[2] if len(parts) > 2 else ""
                        await db_execute("INSERT INTO scheduled_tasks(user_id,task_type,task_data,execute_at) VALUES(?,?,?,?)",
                                       uid, "publish", task_data, dt.isoformat())
                        await update.message.reply_text(f"✅ تم الجدولة: {dt.strftime('%Y-%m-%d %H:%M')}")
                    else:
                        await update.message.reply_text(t(uid, "no_channels"))
                else:
                    await update.message.reply_text(t(uid, "invalid_date"))
            except:
                await update.message.reply_text(t(uid, "invalid_date"))
        else:
            await update.message.reply_text("📝 الصيغة: YYYY-MM-DD HH:MM النص")
        context.user_data.pop("state")
    
    # === دعم ===
    elif state == "SUPPORT":
        if text:
            num = (await db_execute_one("SELECT value FROM settings WHERE key='last_ticket'")) or {"value": "0"}
            new_num = int(num["value"]) + 1
            await db_execute("INSERT INTO tickets(user_id,username,message,num,created_at) VALUES(?,?,?,?,?)",
                           uid, update.effective_user.full_name or str(uid), text, new_num, datetime.now().isoformat())
            await db_execute("UPDATE settings SET value=? WHERE key='last_ticket'", str(new_num))
            await update.message.reply_text(t(uid, "support_ticket", num=new_num), reply_markup=main_keyboard(uid))
            # إشعار للمطور
            try:
                await context.bot.send_message(OWNER, f"📩 تذكرة جديدة #{new_num}\nمن: {uid}\nالرسالة: {text}")
            except:
                pass
        context.user_data.pop("state")
    
    # === إذاعة ===
    elif state == "BROADCAST":
        if uid == OWNER and text:
            users = await db_execute("SELECT user_id FROM users WHERE banned=0")
            sent = 0
            for u in users:
                try:
                    await context.bot.send_message(u["user_id"], text)
                    sent += 1
                    await asyncio.sleep(0.1)
                except:
                    pass
            await update.message.reply_text(t(uid, "broadcast_sent").format(count=sent), reply_markup=main_keyboard(uid))
        context.user_data.pop("state")
    
    # === إنشاء مسابقة ===
    elif state == "CONTEST_TITLE":
        context.user_data["contest_title"] = text
        context.user_data["state"] = "CONTEST_DESC"
        await update.message.reply_text("📝 وصف المسابقة:")
    
    elif state == "CONTEST_DESC":
        context.user_data["contest_desc"] = text
        context.user_data["state"] = "CONTEST_PRIZE"
        await update.message.reply_text("🎁 الجائزة:")
    
    elif state == "CONTEST_PRIZE":
        context.user_data["contest_prize"] = text
        context.user_data["state"] = "CONTEST_END"
        await update.message.reply_text("📅 تاريخ الانتهاء (YYYY-MM-DD):")
    
    elif state == "CONTEST_END":
        try:
            end_date = datetime.strptime(text.strip(), "%Y-%m-%d")
            if end_date <= datetime.now():
                return await update.message.reply_text(t(uid, "invalid_date"))
            await db_execute("INSERT INTO contests(creator_id,title,description,prize,end_date,status,created_at,contest_type) VALUES(?,?,?,?,?,?,?,?)",
                           uid, context.user_data.get("contest_title"), context.user_data.get("contest_desc"),
                           context.user_data.get("contest_prize"), end_date.isoformat(), "active",
                           datetime.now().isoformat(), "raffle")
            await update.message.reply_text(t(uid, "contest_created"), reply_markup=main_keyboard(uid))
        except:
            await update.message.reply_text(t(uid, "invalid_date"))
        context.user_data.clear()
    
    # === إعلان فائز ===
    elif state == "DECLARE_WINNER":
        parts = text.split()
        if len(parts) == 2:
            try:
                contest_id = int(parts[0])
                winner_id = int(parts[1])
                contest = await db_execute_one("SELECT * FROM contests WHERE id=? AND status='active'", contest_id)
                if not contest:
                    return await update.message.reply_text(t(uid, "contest_not_found"))
                if datetime.fromisoformat(contest["end_date"]) > datetime.now():
                    return await update.message.reply_text(t(uid, "contest_expired"))
                await db_execute("UPDATE contests SET status='finished', winner_id=? WHERE id=?", winner_id, contest_id)
                await db_execute("INSERT OR IGNORE INTO contest_winners(contest_id,winner_id,announced_at) VALUES(?,?,?)",
                               contest_id, winner_id, datetime.now().isoformat())
                await update.message.reply_text(t(uid, "contest_declared"))
                try:
                    await context.bot.send_message(winner_id, t(winner_id, "contest_winner_notification", title=contest["title"], prize=contest["prize"]))
                except:
                    pass
            except:
                await update.message.reply_text("❌ استخدام: contest_id user_id")
        else:
            await update.message.reply_text("❌ استخدام: contest_id user_id")
        context.user_data.pop("state")
    
    # === إعدادات المجموعة ===
    elif state and state.startswith("SET_SLOW_"):
        cid = int(state.split("_")[2])
        try:
            seconds = int(text)
            await db_execute("INSERT OR IGNORE INTO group_security(chat_id) VALUES(?)", cid)
            await db_execute("UPDATE group_security SET slow_mode=?, slow_mode_seconds=? WHERE chat_id=?", 
                           seconds > 0, seconds, cid)
            await update.message.reply_text(t(uid, "slow_mode_active", seconds=seconds))
        except:
            await update.message.reply_text(t(uid, "invalid_number"))
        context.user_data.pop("state")
    
    elif state and state.startswith("SET_WELCOME_"):
        cid = int(state.split("_")[2])
        await db_execute("INSERT OR IGNORE INTO group_security(chat_id) VALUES(?)", cid)
        await db_execute("UPDATE group_security SET welcome_msg=? WHERE chat_id=?", text, cid)
        await update.message.reply_text("✅ تم تحديث الترحيب")
        context.user_data.pop("state")
    
    elif state and state.startswith("SET_GOODBYE_"):
        cid = int(state.split("_")[2])
        await db_execute("INSERT OR IGNORE INTO group_security(chat_id) VALUES(?)", cid)
        await db_execute("UPDATE group_security SET goodbye_msg=? WHERE chat_id=?", text, cid)
        await update.message.reply_text("✅ تم تحديث الوداع")
        context.user_data.pop("state")
    
    elif state and state.startswith("ADD_BW_"):
    global _bw_cache
        cid = int(state.split("_")[2])
        await db_execute("INSERT OR IGNORE INTO banned_words(word,chat_id,added_by,added_at) VALUES(?,?,?,?)",
                        text.lower(), cid, uid, datetime.now().isoformat())
        global _bw_cache
        _bw_cache = await load_banned_cache()
        await update.message.reply_text(f"✅ تم إضافة: {text}")
        context.user_data.pop("state")
    global _bw_cache
    
    elif state and state.startswith("DEL_BW_"):
        cid = int(state.split("_")[2])
        await db_execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", text.lower(), cid)
        global _bw_cache
        _bw_cache = await load_banned_cache()
        await update.message.reply_text(f"✅ تم حذف: {text}")
        context.user_data.pop("state")
    
    elif state and state.startswith("ADD_REP_KW_"):
        cid = int(state.split("_")[2])
        context.user_data["rep_keyword"] = text.lower()
        context.user_data["state"] = f"ADD_REP_TXT_{cid}"
        await update.message.reply_text("📝 أرسل الرد:")
    
    elif state and state.startswith("ADD_REP_TXT_"):
        cid = int(state.split("_")[2])
        kw = context.user_data.get("rep_keyword", "")
        if kw:
            await db_execute("INSERT OR REPLACE INTO replies VALUES(?,?)", kw, text)
        await update.message.reply_text("✅ تم إضافة الرد")
        context.user_data.clear()
    
    elif state and state.startswith("DEL_REP_"):
        cid = int(state.split("_")[1])
        await db_execute("DELETE FROM replies WHERE keyword=?", text.lower())
        await update.message.reply_text("✅ تم حذف الرد")
        context.user_data.pop("state")
    
    elif state == "SET_REM_DAYS":
        try:
            days = int(text)
            if 1 <= days <= 30:
                await db_execute("UPDATE reminders SET days_before=? WHERE user_id=?", days, uid)
                await update.message.reply_text(f"✅ تم تعيين التذكير قبل {days} أيام")
            else:
                await update.message.reply_text("❌ يجب أن يكون بين 1 و 30")
        except:
            await update.message.reply_text(t(uid, "invalid_number"))
        context.user_data.pop("state")

# ==================== المهام الخلفية ====================
async def auto_publish_loop(app):
    await asyncio.sleep(10)
    while True:
        try:
            interval = int((await db_execute_one("SELECT value FROM settings WHERE key='publish_interval'"))["value"])
        except:
            interval = 720
        
        try:
            channels = await db_execute("SELECT id, user_id, channel_id FROM channels WHERE auto_publish=1")
            for ch in channels:
                # التحقق من الاشتراك
                if not await has_active_subscription(ch["user_id"]):
                    continue
                # جلب منشور
                post = await db_execute_one("SELECT * FROM posts WHERE channel_db_id=? AND published=0 ORDER BY id LIMIT 1", ch["id"])
                if not post:
                    continue
                try:
                    # ترجمة
                    trans_lang = await db_execute_one("SELECT lang FROM user_translation WHERE user_id=?", ch["user_id"])
                    if trans_lang and trans_lang["lang"] != "off":
                        translated = await auto_translator.translate(post["text"], trans_lang["lang"])
                        if translated and translated != post["text"]:
                            post_text = f"{post['text']}\n\n🌐 {translated}"
                        else:
                            post_text = post["text"]
                    else:
                        post_text = post["text"]
                    
                    # نشر
                    if post["media_type"] == "photo":
                        await app.bot.send_photo(ch["channel_id"], post["media_file_id"], caption=post_text)
                    elif post["media_type"] == "video":
                        await app.bot.send_video(ch["channel_id"], post["media_file_id"], caption=post_text)
                    elif post["media_type"] == "document":
                        await app.bot.send_document(ch["channel_id"], post["media_file_id"], caption=post_text)
                    elif post["media_type"] == "audio":
                        await app.bot.send_audio(ch["channel_id"], post["media_file_id"], caption=post_text)
                    elif post["media_type"] == "voice":
                        await app.bot.send_voice(ch["channel_id"], post["media_file_id"], caption=post_text)
                    elif post["media_type"] == "animation":
                        await app.bot.send_animation(ch["channel_id"], post["media_file_id"], caption=post_text)
                    else:
                        await app.bot.send_message(ch["channel_id"], post_text)
                    
                    await db_execute("UPDATE posts SET published=1 WHERE id=?", post["id"])
                    await add_points(ch["user_id"], 5)
                    
                    # تحديث إحصائيات القناة
                    await db_execute("INSERT OR IGNORE INTO channel_stats(channel_db_id) VALUES(?)", ch["id"])
                    await db_execute("UPDATE channel_stats SET total_posts=total_posts+1, published_posts=published_posts+1, last_post_time=? WHERE channel_db_id=?", 
                                   datetime.now().isoformat(), ch["id"])
                    
                except Exception as e:
                    logger.error(f"فشل النشر: {e}")
                    await db_execute("UPDATE posts SET fail_count=fail_count+1 WHERE id=?", post["id"])
                    if post["fail_count"] >= 3:
                        await db_execute("UPDATE posts SET published=1 WHERE id=?", post["id"])  # تخطي المنشور الفاشل
                
                await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"خطأ في حلقة النشر: {e}")
        
        await asyncio.sleep(interval)

async def scheduled_tasks_loop(app):
    await asyncio.sleep(20)
    while True:
        try:
            tasks = await db_execute("SELECT * FROM scheduled_tasks WHERE executed=0 AND execute_at <= ?", 
                                    datetime.now().isoformat())
            for task in tasks:
                if task["task_type"] == "publish":
                    ch = await db_execute_one("SELECT id,channel_id FROM channels WHERE user_id=? AND active_channel=id LIMIT 1", 
                                            task["user_id"])
                    if ch:
                        try:
                            await app.bot.send_message(ch["channel_id"], task["task_data"])
                        except:
                            pass
                await db_execute("UPDATE scheduled_tasks SET executed=1 WHERE id=?", task["id"])
        except:
            pass
        await asyncio.sleep(10)

async def reminder_loop(app):
    await asyncio.sleep(30)
    while True:
        try:
            reminders = await db_execute("SELECT * FROM reminders WHERE sub=1")
            for rem in reminders:
                sub = await db_execute_one("SELECT subscription_end FROM users WHERE user_id=?", rem["user_id"])
                if sub and sub["subscription_end"]:
                    try:
                        end_str = dec(sub["subscription_end"])
                        if end_str:
                            days = (datetime.fromisoformat(end_str) - datetime.now()).days
                            if 0 < days <= rem["days_before"]:
                                last = rem.get("last_reminder_sent", 0)
                                now_ts = int(time.time())
                                if now_ts - last > 86400:  # مرة واحدة في اليوم
                                    try:
                                        await app.bot.send_message(rem["user_id"], 
                                            t(rem["user_id"], "subscription_warning").format(days=days))
                                        await db_execute("UPDATE reminders SET last_reminder_sent=? WHERE user_id=?", 
                                                       now_ts, rem["user_id"])
                                    except:
                                        pass
                    except:
                        pass
        except:
            pass
        await asyncio.sleep(3600)

async def daily_report_loop(app):
    await asyncio.sleep(60)
    while True:
        try:
            now = datetime.now()
            # كل يوم الساعة 8 صباحاً
            if now.hour == 8 and now.minute == 0:
                users = await db_execute("SELECT user_id, daily FROM reminders WHERE daily=1")
                for u in users:
                    try:
                        channels = len(await db_execute("SELECT 1 FROM channels WHERE user_id=?", u["user_id"]))
                        total_posts = len(await db_execute("SELECT 1 FROM posts WHERE channel_db_id IN (SELECT id FROM channels WHERE user_id=?)", u["user_id"]))
                        unpublished = len(await db_execute("SELECT 1 FROM posts WHERE channel_db_id IN (SELECT id FROM channels WHERE user_id=?) AND published=0", u["user_id"]))
                        groups = len(await db_execute("SELECT 1 FROM groups WHERE added_by=?", u["user_id"]))
                        text = t(u["user_id"], "daily_stats", ch=channels, posts=total_posts, unpub=unpublished, groups=groups)
                        await app.bot.send_message(u["user_id"], text)
                    except:
                        pass
        except:
            pass
        await asyncio.sleep(60)

async def weekly_report_loop(app):
    await asyncio.sleep(120)
    while True:
        try:
            now = datetime.now()
            # كل يوم أحد الساعة 9 صباحاً
            if now.weekday() == 6 and now.hour == 9 and now.minute == 0:
                users = await db_execute("SELECT user_id, weekly FROM reminders WHERE weekly=1")
                for u in users:
                    try:
                        channels = len(await db_execute("SELECT 1 FROM channels WHERE user_id=?", u["user_id"]))
                        total_posts = len(await db_execute("SELECT 1 FROM posts WHERE channel_db_id IN (SELECT id FROM channels WHERE user_id=?)", u["user_id"]))
                        unpublished = len(await db_execute("SELECT 1 FROM posts WHERE channel_db_id IN (SELECT id FROM channels WHERE user_id=?) AND published=0", u["user_id"]))
                        groups = len(await db_execute("SELECT 1 FROM groups WHERE added_by=?", u["user_id"]))
                        referrals = len(await db_execute("SELECT 1 FROM referrals WHERE ref_id=?", u["user_id"]))
                        text = t(u["user_id"], "weekly_report", ch=channels, posts=total_posts, unpub=unpublished, groups=groups, refs=referrals)
                        await app.bot.send_message(u["user_id"], text)
                    except:
                        pass
        except:
            pass
        await asyncio.sleep(60)

async def self_ping_loop():
    if not RENDER_URL:
        return
    await asyncio.sleep(60)
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                await session.get(f"{RENDER_URL}/health", timeout=10)
        except:
            pass
        await asyncio.sleep(300)

# ==================== خادم الويب ====================
WEB_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ريلاكس مانيجر - لوحة التحكم</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background: #f8f9fa; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .sidebar { min-height: 100vh; background: #2d3436; color: white; padding: 20px; position: fixed; right: 0; top: 0; width: 250px; }
        .sidebar .brand { font-size: 24px; font-weight: bold; padding: 20px 0; border-bottom: 1px solid #444; }
        .sidebar .nav-link { color: rgba(255,255,255,0.7); padding: 12px 15px; border-radius: 10px; margin-bottom: 5px; }
        .sidebar .nav-link:hover { background: rgba(255,255,255,0.1); color: white; }
        .sidebar .nav-link.active { background: #0984e3; color: white; }
        .main-content { margin-right: 250px; padding: 20px; }
        .stat-card { background: white; border-radius: 15px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); border-right: 4px solid #0984e3; }
        .stat-card .stat-number { font-size: 28px; font-weight: bold; }
        .stat-card .stat-label { color: #636e72; font-size: 14px; }
        .chart-container { height: 300px; margin: 20px 0; }
        .status-badge { padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: bold; }
        .status-badge.active { background: #d4edda; color: #155724; }
        .status-badge.banned { background: #f8d7da; color: #721c24; }
        .webhook-status { display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 5px; }
        .webhook-status.online { background: #00b894; }
        .webhook-status.offline { background: #e17055; }
        @media (max-width: 768px) { .sidebar { position: static; width: 100%; min-height: auto; } .main-content { margin-right: 0; } }
    </style>
</head>
<body>
<div class="sidebar">
    <div class="brand text-center"><i class="bi bi-robot"></i> ريلاكس مانيجر</div>
    <nav class="nav flex-column mt-3">
        <a class="nav-link active" href="#" data-page="dashboard"><i class="bi bi-speedometer2"></i> لوحة التحكم</a>
        <a class="nav-link" href="#" data-page="users"><i class="bi bi-people"></i> المستخدمين</a>
        <a class="nav-link" href="#" data-page="channels"><i class="bi bi-broadcast"></i> القنوات</a>
        <a class="nav-link" href="#" data-page="groups"><i class="bi bi-chat-dots"></i> المجموعات</a>
        <a class="nav-link" href="#" data-page="posts"><i class="bi bi-file-post"></i> المنشورات</a>
        <a class="nav-link" href="#" data-page="contests"><i class="bi bi-trophy"></i> المسابقات</a>
        <a class="nav-link" href="#" data-page="backups"><i class="bi bi-archive"></i> النسخ الاحتياطية</a>
        <a class="nav-link" href="#" data-page="settings"><i class="bi bi-gear"></i> الإعدادات</a>
        <hr class="border-secondary">
        <a class="nav-link text-danger" href="#" onclick="logout()"><i class="bi bi-box-arrow-left"></i> خروج</a>
    </nav>
</div>
<div class="main-content">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2 id="page-title">لوحة التحكم</h2>
        <div><span class="webhook-status online" id="ws-status"></span><span id="ws-status-text">متصل</span></div>
    </div>
    <div id="page-dashboard">
        <div class="row" id="stats-cards">
            <div class="col-md-3"><div class="stat-card"><div class="stat-number" id="stat-users">0</div><div class="stat-label">المستخدمين</div></div></div>
            <div class="col-md-3"><div class="stat-card"><div class="stat-number" id="stat-channels">0</div><div class="stat-label">القنوات</div></div></div>
            <div class="col-md-3"><div class="stat-card"><div class="stat-number" id="stat-groups">0</div><div class="stat-label">المجموعات</div></div></div>
            <div class="col-md-3"><div class="stat-card"><div class="stat-number" id="stat-posts">0</div><div class="stat-label">منشورات غير منشورة</div></div></div>
        </div>
        <div class="row">
            <div class="col-md-6"><div class="card"><div class="card-header">نمو المستخدمين</div><div class="card-body"><div class="chart-container"><canvas id="growthChart"></canvas></div></div></div></div>
            <div class="col-md-6"><div class="card"><div class="card-header">توزيع المنشورات</div><div class="card-body"><div class="chart-container"><canvas id="distributionChart"></canvas></div></div></div></div>
        </div>
        <div class="row mt-3"><div class="col-md-6"><div class="card"><div class="card-header">معلومات النظام</div><div class="card-body" id="system-info"><div class="d-flex justify-content-between border-bottom py-2"><span>حالة البوت</span><span class="status-badge active">🟢 يعمل</span></div><div class="d-flex justify-content-between border-bottom py-2"><span>الإصدار</span><span>20.0.3</span></div><div class="d-flex justify-content-between border-bottom py-2"><span>وقت التشغيل</span><span id="uptime">0 ساعة</span></div><div class="d-flex justify-content-between py-2"><span>استخدام الذاكرة</span><span id="memory">0%</span></div></div></div></div></div>
    </div>
    <div id="page-users" style="display:none;"><div class="card"><div class="card-header">المستخدمين</div><div class="card-body"><div class="table-responsive"><table class="table"><thead><tr><th>#</th><th>المعرف</th><th>الحالة</th><th>النقاط</th><th>المستوى</th></tr></thead><tbody id="users-tbody"></tbody></table></div></div></div></div>
    <div id="page-channels" style="display:none;"><div class="card"><div class="card-header">القنوات</div><div class="card-body"><div class="table-responsive"><table class="table"><thead><tr><th>#</th><th>المستخدم</th><th>القناة</th><th>الاسم</th><th>الحالة</th></tr></thead><tbody id="channels-tbody"></tbody></table></div></div></div></div>
    <div id="page-groups" style="display:none;"><div class="card"><div class="card-header">المجموعات</div><div class="card-body"><div class="table-responsive"><table class="table"><thead><tr><th>#</th><th>المعرف</th><th>الاسم</th><th>المستخدم</th><th>الحالة</th></tr></thead><tbody id="groups-tbody"></tbody></table></div></div></div></div>
    <div id="page-posts" style="display:none;"><div class="card"><div class="card-header">المنشورات غير المنشورة</div><div class="card-body"><div class="table-responsive"><table class="table"><thead><tr><th>#</th><th>القناة</th><th>النص</th><th>النوع</th><th>التاريخ</th></tr></thead><tbody id="posts-tbody"></tbody></table></div></div></div></div>
    <div id="page-contests" style="display:none;"><div class="card"><div class="card-header">المسابقات</div><div class="card-body"><div class="table-responsive"><table class="table"><thead><tr><th>#</th><th>العنوان</th><th>الجائزة</th><th>المشاركون</th><th>التاريخ</th><th>الحالة</th></tr></thead><tbody id="contests-tbody"></tbody></table></div></div></div></div>
    <div id="page-backups" style="display:none;"><div class="card"><div class="card-header">النسخ الاحتياطية</div><div class="card-body"><div class="table-responsive"><table class="table"><thead><tr><th>#</th><th>الملف</th><th>الحجم</th><th>التاريخ</th><th>الإجراءات</th></tr></thead><tbody id="backups-tbody"></tbody></table></div></div></div></div>
    <div id="page-settings" style="display:none;"><div class="card"><div class="card-header">الإعدادات</div><div class="card-body"><form id="settings-form"><div class="mb-3"><label>وقت النشر (ثانية)</label><input type="number" class="form-control" id="publish-interval" value="720"></div><div class="mb-3"><label>قناة التحديثات</label><input type="text" class="form-control" id="updates-channel" placeholder="@channel"></div><button type="submit" class="btn btn-primary">حفظ</button></form></div></div></div></div>
</div>
<script>
let ws = null;
function connectWS() {
    ws = new WebSocket(`ws://${window.location.host}/ws`);
    ws.onopen = function() { document.getElementById('ws-status').className = 'webhook-status online'; document.getElementById('ws-status-text').textContent = 'متصل'; };
    ws.onclose = function() { document.getElementById('ws-status').className = 'webhook-status offline'; document.getElementById('ws-status-text').textContent = 'غير متصل'; setTimeout(connectWS, 5000); };
    ws.onmessage = function(e) {
        try {
            const data = JSON.parse(e.data);
            if (data.type === 'stats') updateStats(data.data);
        } catch(err) {}
    };
}
function updateStats(data) {
    document.getElementById('stat-users').textContent = data.total_users || 0;
    document.getElementById('stat-channels').textContent = data.channels || 0;
    document.getElementById('stat-groups').textContent = data.groups || 0;
    document.getElementById('stat-posts').textContent = data.pending_posts || 0;
}
function logout() { document.cookie = 'session_id=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;'; window.location.href = '/logout'; }
document.querySelectorAll('.sidebar .nav-link').forEach(link => {
    link.addEventListener('click', function(e) {
        e.preventDefault();
        document.querySelectorAll('.sidebar .nav-link').forEach(l => l.classList.remove('active'));
        this.classList.add('active');
        const page = this.dataset.page;
        document.querySelectorAll('.main-content > div[id^="page-"]').forEach(p => p.style.display = 'none');
        const target = document.getElementById(`page-${page}`);
        if (target) { target.style.display = 'block'; document.getElementById('page-title').textContent = this.textContent.trim(); }
        if (page === 'dashboard') refreshDashboard();
        else if (page === 'users') fetch('/api/users').then(r=>r.json()).then(data => {
            const tbody = document.getElementById('users-tbody');
            tbody.innerHTML = data.map((u,i) => `<tr><td>${i+1}</td><td><code>${u.user_id}</code></td><td><span class="status-badge ${u.banned?'banned':'active'}">${u.banned?'🚫 محظور':'✅ نشط'}</span></td><td>${u.points||0}</td><td>${u.level||1}</td></tr>`).join('');
        });
        else if (page === 'channels') fetch('/api/channels').then(r=>r.json()).then(data => {
            document.getElementById('channels-tbody').innerHTML = data.map((c,i) => `<tr><td>${i+1}</td><td><code>${c.user_id}</code></td><td><code>${c.channel_id}</code></td><td>${c.channel_name||c.channel_id}</td><td><span class="status-badge ${c.banned?'banned':'active'}">${c.banned?'⛔':'✅'}</span></td></tr>`).join('');
        });
        else if (page === 'groups') fetch('/api/groups').then(r=>r.json()).then(data => {
            document.getElementById('groups-tbody').innerHTML = data.map((g,i) => `<tr><td>${i+1}</td><td><code>${g.chat_id}</code></td><td>${g.chat_name||g.chat_id}</td><td><code>${g.added_by}</code></td><td><span class="status-badge ${g.banned?'banned':'active'}">${g.banned?'⛔':'✅'}</span></td></tr>`).join('');
        });
        else if (page === 'posts') fetch('/api/posts').then(r=>r.json()).then(data => {
            document.getElementById('posts-tbody').innerHTML = data.map((p,i) => `<tr><td>${i+1}</td><td>${p.channel_name||p.channel_id}</td><td>${(p.text||'').substring(0,30)}...</td><td><span class="badge bg-secondary">${p.media_type||'text'}</span></td><td>${p.created_at?new Date(p.created_at).toLocaleDateString('ar-EG'):'-'}</td></tr>`).join('');
        });
        else if (page === 'contests') fetch('/api/contests').then(r=>r.json()).then(data => {
            document.getElementById('contests-tbody').innerHTML = data.map((c,i) => `<tr><td>${i+1}</td><td>${c.title||'بدون'}</td><td>${c.prize||'-'}</td><td>${c.participants||0}</td><td>${c.end_date?new Date(c.end_date).toLocaleDateString('ar-EG'):'-'}</td><td><span class="status-badge ${c.status==='active'?'active':'banned'}">${c.status==='active'?'نشطة':'منتهية'}</span></td></tr>`).join('');
        });
        else if (page === 'backups') fetch('/api/backups').then(r=>r.json()).then(data => {
            document.getElementById('backups-tbody').innerHTML = data.map((b,i) => `<tr><td>${i+1}</td><td>${b.name}</td><td>${(b.size/1024).toFixed(2)}KB</td><td>${b.date||'-'}</td><td><button class="btn btn-sm btn-success" onclick="restore('${b.name}')">استعادة</button></td></tr>`).join('');
        });
        else if (page === 'settings') fetch('/api/settings').then(r=>r.json()).then(data => {
            document.getElementById('publish-interval').value = data.publish_interval||720;
            document.getElementById('updates-channel').value = data.updates_channel||'';
        });
    });
});
function refreshDashboard() {
    fetch('/api/stats').then(r=>r.json()).then(data => updateStats(data));
    fetch('/api/system-info').then(r=>r.json()).then(data => {
        document.getElementById('uptime').textContent = data.uptime||'0 ساعة';
        document.getElementById('memory').textContent = data.memory||'0%';
    });
    fetch('/api/charts').then(r=>r.json()).then(data => {
        if (window.growthChart) { window.growthChart.data.labels = data.user_growth.labels||[]; window.growthChart.data.datasets[0].data = data.user_growth.data||[]; window.growthChart.update(); }
        if (window.distChart) { window.distChart.data.datasets[0].data = [data.posts_distribution.published||0, data.posts_distribution.unpublished||0]; window.distChart.update(); }
    });
}
function restore(name) { if(confirm(`استعادة ${name}?`)) fetch(`/api/backups/${encodeURIComponent(name)}/restore`, {method:'POST'}).then(()=>location.reload()); }
document.addEventListener('DOMContentLoaded', function() {
    connectWS();
    const ctx1 = document.getElementById('growthChart').getContext('2d');
    window.growthChart = new Chart(ctx1, { type: 'line', data: { labels: [], datasets: [{ label: 'المستخدمين', data: [], borderColor: '#0984e3', fill: true }] }, options: { responsive: true, maintainAspectRatio: false } });
    const ctx2 = document.getElementById('distributionChart').getContext('2d');
    window.distChart = new Chart(ctx2, { type: 'doughnut', data: { labels: ['منشورة', 'غير منشورة'], datasets: [{ data: [0, 0], backgroundColor: ['#00b894', '#e17055'] }] }, options: { responsive: true, maintainAspectRatio: false } });
    refreshDashboard();
    document.getElementById('page-dashboard').style.display = 'block';
    document.getElementById('settings-form').addEventListener('submit', function(e) {
        e.preventDefault();
        fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ publish_interval: parseInt(document.getElementById('publish-interval').value)||720, updates_channel: document.getElementById('updates-channel').value }) })
        .then(r=>r.json()).then(data => alert(data.message||'✅ تم الحفظ'));
    });
    setInterval(() => { if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' })); }, 30000);
});
</script>
</body>
</html>"""

WEB_SESSIONS = {}
BOT_START_TIME = time.time()

async def web_auth_middleware(request, handler):
    session_id = request.cookies.get('session_id')
    if session_id and session_id in WEB_SESSIONS:
        return await handler(request)
    auth = request.headers.get('Authorization')
    if auth and auth.startswith('Basic '):
        try:
            decoded = base64.b64decode(auth.split(' ')[1]).decode()
            username, password = decoded.split(':', 1)
            if username == WEB_USERNAME and password == WEB_PASSWORD:
                sid = secrets.token_urlsafe(32)
                WEB_SESSIONS[sid] = {'user': username}
                response = await handler(request)
                response.set_cookie('session_id', sid, httponly=True, max_age=3600)
                return response
        except: pass
    return web.Response(status=401, headers={'WWW-Authenticate': 'Basic realm="Login"'})

async def web_root(request):
    return web.Response(text=WEB_HTML, content_type='text/html')

async def web_logout(request):
    response = web.Response(status=302, headers={'Location': '/'})
    response.del_cookie('session_id')
    return response

async def api_stats(request):
    total = len(await db_execute("SELECT 1 FROM users"))
    banned = len(await db_execute("SELECT 1 FROM users WHERE banned=1"))
    posts = len(await db_execute("SELECT 1 FROM posts WHERE published=0"))
    groups = len(await db_execute("SELECT 1 FROM groups"))
    channels = len(await db_execute("SELECT 1 FROM channels"))
    return web.json_response({'total_users': total, 'banned_users': banned, 'pending_posts': posts, 'groups': groups, 'channels': channels})

async def api_users(request):
    users = await db_execute("SELECT user_id, banned, points, level FROM users LIMIT 100")
    return web.json_response([dict(u) for u in users])

async def api_channels(request):
    channels = await db_execute("SELECT user_id, channel_id, channel_name, banned FROM channels LIMIT 100")
    return web.json_response([dict(c) for c in channels])

async def api_groups(request):
    groups = await db_execute("SELECT chat_id, chat_name, added_by, banned FROM groups LIMIT 100")
    return web.json_response([dict(g) for g in groups])

async def api_posts(request):
    posts = await db_execute("SELECT p.id, p.text, p.media_type, p.created_at, c.channel_name, c.channel_id FROM posts p JOIN channels c ON p.channel_db_id=c.id WHERE p.published=0 LIMIT 100")
    return web.json_response([dict(p) for p in posts])

async def api_contests(request):
    contests = await db_execute("SELECT id, title, prize, end_date, status, (SELECT COUNT(*) FROM contest_parts WHERE contest_id=c.id) as participants FROM contests c ORDER BY id DESC LIMIT 50")
    return web.json_response([dict(c) for c in contests])

async def api_backups(request):
    backups = sorted(Path('data').glob('backup_*.db'), key=lambda x: x.stat().st_mtime, reverse=True)
    return web.json_response([{'name': b.name, 'size': b.stat().st_size, 'date': datetime.fromtimestamp(b.stat().st_mtime).strftime('%Y-%m-%d %H:%M')} for b in backups])

async def api_restore_backup(request):
    name = request.match_info.get('name')
    if name:
        src = Path('data') / name
        if src.exists():
            shutil.copy2(src, DB_PATH)
            return web.json_response({'status': 'ok', 'message': '✅ تم الاستعادة'})
    return web.json_response({'status': 'error', 'message': '❌ غير موجود'}, status=404)

async def api_system_info(request):
    mem = psutil.virtual_memory()
    uptime = int(time.time() - BOT_START_TIME)
    hours = uptime // 3600
    minutes = (uptime % 3600) // 60
    return web.json_response({
        'uptime': f'{hours} ساعة {minutes} دقيقة',
        'memory': f"{mem.percent}%",
        'version': '20.0.3'
    })

async def api_settings(request):
    if request.method == 'GET':
        interval = await db_execute_one("SELECT value FROM settings WHERE key='publish_interval'")
        channel = await db_execute_one("SELECT value FROM settings WHERE key='updates_channel'")
        return web.json_response({
            'publish_interval': int(interval['value']) if interval else 720,
            'updates_channel': channel['value'] if channel else ''
        })
    elif request.method == 'POST':
        data = await request.json()
        interval = data.get('publish_interval', 720)
        channel = data.get('updates_channel', '')
        await db_execute("INSERT OR REPLACE INTO settings VALUES('publish_interval', ?)", str(interval))
        await db_execute("INSERT OR REPLACE INTO settings VALUES('updates_channel', ?)", channel)
        return web.json_response({'status': 'ok', 'message': '✅ تم الحفظ'})

async def api_charts(request):
    return web.json_response({
        'user_growth': {'labels': ['اليوم', 'أمس', 'قبل 3 أيام', 'قبل 4 أيام', 'قبل 5 أيام', 'قبل 6 أيام', 'قبل أسبوع'], 'data': [100, 95, 90, 85, 80, 75, 70]},
        'posts_distribution': {'published': 120, 'unpublished': 45}
    })

async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    async for msg in ws:
        if msg.type == web.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
                if data.get('type') == 'ping':
                    await ws.send_str(json.dumps({'type': 'pong'}))
            except: pass
    return ws

async def start_web_server():
    from aiohttp import web
    app = web.Application(middlewares=[web_auth_middleware])
    app.router.add_get('/', web_root)
    app.router.add_get('/logout', web_logout)
    app.router.add_get('/api/stats', api_stats)
    app.router.add_get('/api/users', api_users)
    app.router.add_get('/api/channels', api_channels)
    app.router.add_get('/api/groups', api_groups)
    app.router.add_get('/api/posts', api_posts)
    app.router.add_get('/api/contests', api_contests)
    app.router.add_get('/api/backups', api_backups)
    app.router.add_post('/api/backups/{name}/restore', api_restore_backup)
    app.router.add_get('/api/system-info', api_system_info)
    app.router.add_get('/api/settings', api_settings)
    app.router.add_post('/api/settings', api_settings)
    app.router.add_get('/api/charts', api_charts)
    app.router.add_get('/ws', websocket_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    logger.info(f"✅ خادم الويب: http://0.0.0.0:{PORT}")
    logger.info(f"🔑 الدخول: {WEB_USERNAME} / {WEB_PASSWORD}")

# ==================== الدالة الرئيسية ====================
async def main():
    await get_db()
    app = Application.builder().token(TOKEN).build()
    # تسجيل المعالجات
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, auto_register_group), group=1)
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_user_join), group=2)
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_user_leave))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ping", ping_command))
    app.add_handler(CommandHandler("reload", reload_command))
    app.add_handler(CommandHandler("panel", panel_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("claim", claim))
    app.add_handler(CommandHandler("addowner", add_owner))
    app.add_handler(CommandHandler("addadmin", add_admin))
    app.add_handler(CommandHandler("remove", remove_admin))
    app.add_handler(CommandHandler("list", list_admins))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("unban", unban_user))
    app.add_handler(CommandHandler("mute", mute_user))
    app.add_handler(CommandHandler("unmute", unmute_user))
    app.add_handler(CommandHandler("kick", kick_user))
    app.add_handler(CommandHandler("pin", pin_message))
    app.add_handler(CommandHandler("unpin", unpin_message))
    app.add_handler(CommandHandler("promote", promote_user))
    app.add_handler(CommandHandler("demote", demote_user))
    app.add_handler(CommandHandler("purge", purge_messages))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CommandHandler("warn", warn_user))
    app.add_handler(CommandHandler("transfer", transfer_ownership))
    app.add_handler(CommandHandler("report", lambda u,c: u.message.reply_text("✅")))
    app.add_handler(CommandHandler("lock_links", lock_links))
    app.add_handler(CommandHandler("unlock_links", unlock_links))
    app.add_handler(CommandHandler("lock_mentions", lock_mentions))
    app.add_handler(CommandHandler("unlock_mentions", unlock_mentions))
    app.add_handler(CommandHandler("slowmode", slowmode_command))
    app.add_handler(CommandHandler("welcome", welcome_command))
    app.add_handler(CommandHandler("goodbye", goodbye_command))
    app.add_handler(CommandHandler("add_banned", add_banned_word))
    app.add_handler(CommandHandler("remove_banned", remove_banned_word))
    app.add_handler(CommandHandler("list_banned", list_banned_words))
    app.add_handler(CommandHandler("add_reply", add_reply))
    app.add_handler(CommandHandler("remove_reply", remove_reply))
    app.add_handler(CommandHandler("list_replies", list_replies))
    app.add_handler(CommandHandler("log", log_command))
    app.add_handler(CommandHandler("settings", group_settings))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, payment_callback))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, group_message_filter))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, private_message_handler))
    await app.bot.set_my_commands([
        BotCommand("start","بدء"), BotCommand("help","مساعدة"), BotCommand("ping","فحص"),
        BotCommand("claim","مالك مخفي"), BotCommand("addowner","+مالك"), BotCommand("addadmin","+مشرف"),
        BotCommand("remove","إزالة"), BotCommand("list","عرض"), BotCommand("ban","حظر"), BotCommand("unban","فك"),
        BotCommand("mute","كتم"), BotCommand("unmute","فك"), BotCommand("kick","طرد"), BotCommand("pin","تثبيت"),
        BotCommand("unpin","إلغاء"), BotCommand("promote","ترقية"), BotCommand("demote","تنزيل"),
        BotCommand("purge","حذف"), BotCommand("info","معلومات"), BotCommand("warn","تحذير"),
        BotCommand("transfer","نقل"), BotCommand("lock_links","قفل روابط"), BotCommand("unlock_links","فتح"),
        BotCommand("lock_mentions","قفل @"), BotCommand("unlock_mentions","فتح"),
        BotCommand("slowmode","بطيء"), BotCommand("welcome","ترحيب"), BotCommand("goodbye","وداع"),
        BotCommand("add_banned","+كلمة"), BotCommand("remove_banned","-كلمة"), BotCommand("list_banned","كلمات"),
        BotCommand("add_reply","+رد"), BotCommand("remove_reply","-رد"), BotCommand("list_replies","ردود"),
        BotCommand("log","سجل"), BotCommand("settings","إعدادات"), BotCommand("panel","لوحة تحكم"),
        BotCommand("broadcast","إذاعة"),
    ])
    asyncio.create_task(auto_publish_loop(app))
    asyncio.create_task(scheduled_tasks_loop(app))
    asyncio.create_task(reminder_loop(app))
    asyncio.create_task(daily_report_loop(app))
    asyncio.create_task(weekly_report_loop(app))
    asyncio.create_task(start_web_server())
    logger.info(f"✅ {BOT_NAME} v20.0.3 - جميع الأنظمة متكاملة")
    logger.info(f"🔑 واجهة الويب: {WEB_USERNAME} / {WEB_PASSWORD}")
    try:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        while True: await asyncio.sleep(3600)
    finally:
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: logger.info("🛑 توقف")
    except Exception as e: logger.error(f"❌ {e}"); traceback.print_exc()
