#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ريلاكس مانيجر - بوت متكامل لإدارة القنوات والمجموعات
الإصدار: 19.3.3 - إضافة أزرار حذف الفيديوهات ورسائل الخدمة والملفات والملصقات
المطور: @RelaxMgr
"""

import sys
import os
from pathlib import Path
import secrets
import string
import urllib.parse
import base64
import io
import tempfile
import json
import hashlib
import hmac
import time as time_module
import re
import shutil
import logging
import traceback
import random
import asyncio
import socket
import subprocess
import gc
import sqlite3
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
from typing import Optional, List, Dict, Tuple, Any, Union, Callable, Awaitable
from functools import lru_cache, wraps
from dataclasses import dataclass, asdict
from enum import Enum, auto
import gzip
import zipfile
import platform
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import queue
from concurrent.futures import ThreadPoolExecutor
import types

# ===================== التحقق من إصدار بايثون =====================
def check_python_version():
    required_version = (3, 8)
    current_version = sys.version_info
    if current_version < required_version:
        print(f"❌ يحتاج البوت إلى بايثون {required_version[0]}.{required_version[1]} أو أحدث")
        print(f"📌 الإصدار الحالي: {current_version[0]}.{current_version[1]}")
        sys.exit(1)

check_python_version()

# ===================== تعريف JINJA2_AVAILABLE قبل الاستخدام =====================
JINJA2_AVAILABLE = False
try:
    import jinja2
    JINJA2_AVAILABLE = True
except ImportError:
    print("⚠️ Jinja2 غير متاح - سيتم استخدام HTML النقي")

# ===================== المسارات الأساسية =====================
def get_base_path() -> Path:
    return Path(__file__).parent.resolve()

BASE_PATH = get_base_path()

def get_writable_path(base_path: Path, subdir: str) -> Path:
    paths_to_try = [
        base_path / subdir,
        Path.home() / f".bot_{subdir}",
        Path(f"/tmp/bot_{subdir}"),
        Path(os.getenv('TEMP', '/tmp')) / f"bot_{subdir}",
    ]
    for path in paths_to_try:
        try:
            path.mkdir(parents=True, exist_ok=True)
            test_file = path / ".write_test"
            test_file.touch()
            test_file.unlink()
            return path
        except:
            continue
    import tempfile
    temp_path = Path(tempfile.gettempdir()) / f"bot_{subdir}"
    temp_path.mkdir(parents=True, exist_ok=True)
    return temp_path

def get_temp_path() -> Path:
    return get_writable_path(BASE_PATH, "temp")

DATA_PATH = get_writable_path(BASE_PATH, "data")
DB_PATH = DATA_PATH / "bot_data.db"
BACKUP_DIR = get_writable_path(BASE_PATH, "backups")
LOG_PATH = get_writable_path(BASE_PATH, "logs") / "bot.log"
SECURITY_LOG = get_writable_path(BASE_PATH, "logs") / "security.log"
ERROR_LOG = get_writable_path(BASE_PATH, "logs") / "errors.log"
ACCESS_LOG = get_writable_path(BASE_PATH, "logs") / "access.log"
TEMP_PATH = get_temp_path()
STATIC_PATH = get_writable_path(BASE_PATH, "static")
TEMPLATES_PATH = get_writable_path(BASE_PATH, "templates")
LANG_PATH = BASE_PATH / "lang"

BACKUP_DIR.mkdir(parents=True, exist_ok=True)
DATA_PATH.mkdir(parents=True, exist_ok=True)
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
TEMP_PATH.mkdir(parents=True, exist_ok=True)
STATIC_PATH.mkdir(parents=True, exist_ok=True)
TEMPLATES_PATH.mkdir(parents=True, exist_ok=True)
LANG_PATH.mkdir(parents=True, exist_ok=True)

# ===================== التثبيت التلقائي للمكتبات =====================
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
ensure_package("cachetools")
ensure_package("psutil")
ensure_package("nest-asyncio", "nest_asyncio")
ensure_package("aiosqlite")
ensure_package("cryptography")
ensure_package("deep-translator", "deep_translator")
ensure_package("bleach")
ensure_package("qrcode")
ensure_package("Pillow", "PIL")
ensure_package("plotly")
ensure_package("aiohttp")
ensure_package("aiofiles")
ensure_package("httpx")
ensure_package("reportlab")
ensure_package("jinja2")
ensure_package("markdown")
ensure_package("python-multipart", "multipart")

# محاولة تثبيت المكتبات الاختيارية
PYOTP_AVAILABLE = ensure_package("pyotp")
ZSTD_AVAILABLE = ensure_package("zstandard")
CV2_AVAILABLE = ensure_package("opencv-python-headless", "cv2")
GOOGLE_AUTH_AVAILABLE = False
try:
    ensure_package("google-auth", "google.auth")
    ensure_package("google-auth-oauthlib", "google_auth_oauthlib")
    ensure_package("google-api-python-client", "googleapiclient")
    GOOGLE_AUTH_AVAILABLE = True
except:
    GOOGLE_AUTH_AVAILABLE = False

if PYOTP_AVAILABLE:
    import pyotp

if ZSTD_AVAILABLE:
    import zstandard
    ZSTD_COMPRESSOR = zstandard.ZstdCompressor(level=3)
    ZSTD_DECOMPRESSOR = zstandard.ZstdDecompressor()

if CV2_AVAILABLE:
    import cv2
    import numpy as np

if GOOGLE_AUTH_AVAILABLE:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

# ===================== استيراد المكتبات =====================
import nest_asyncio
nest_asyncio.apply()

import aiosqlite
from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, BotCommand, LabeledPrice, ChatPermissions
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, PreCheckoutQueryHandler, ChatMemberHandler
from telegram.error import TimedOut, NetworkError, BadRequest, Forbidden, Conflict
from telegram.request import HTTPXRequest
import httpx
from deep_translator import GoogleTranslator
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from aiohttp import web, WSMsgType
import aiohttp
from PIL import Image
import numpy as np

# ===================== نظام اللغات من ملفات منفصلة =====================
_lang_data = {}
_lang_cache_time = {}
LANG_CACHE_TTL = 300

def load_all_languages():
    """تحميل جميع ملفات اللغة"""
    global _lang_data
    for lang_file in LANG_PATH.glob("*.json"):
        lang = lang_file.stem
        try:
            with open(lang_file, 'r', encoding='utf-8') as f:
                _lang_data[lang] = json.load(f)
            print(f"✅ تم تحميل اللغة: {lang}")
        except Exception as e:
            print(f"⚠️ فشل تحميل {lang_file}: {e}")
    
    if not _lang_data:
        create_default_lang_files()
        load_all_languages()

def create_default_lang_files():
    """إنشاء ملفات اللغة الافتراضية"""
    default_langs = {
        'ar': {
            "welcome": "🌿 **مرحباً بك في ريلاكس مانيجر**\nاختر اللغة المناسبة",
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
            "send_channel_id": "📡 أرسل معرف القناة (مثال: @RelaxMgrr أو -100123456)",
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
            "help": "❓ **المساعدة**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 **الأوامر المتاحة:**\n/start - القائمة الرئيسية\n/trial - تجربة مجانية\n/subscribe - الاشتراك\n/syncgroup - تفعيل المجموعة\n/security - إعدادات الأمان\n/register_hidden_owner - تسجيل مالك مخفي\n/add_hidden_admin - إضافة مشرف مخفي\n/remove_hidden_admin - إزالة مشرف مخفي\n/list_hidden_admins - عرض المشرفين المخفيين\n/rank - رتبتك\n/top - أفضل 10\n/stats - إحصائيات القناة\n/lock - قفل المجموعة\n/unlock - فتح المجموعة\n/schedule - جدولة منشور\n/panel - لوحة التحكم\n/language - تغيير اللغة\n/support - مركز الدعم\n/help - هذه المساعدة\n/developer - المطور\n/updates - التحديثات\n/contests - المسابقات\n/create_contest - إنشاء مسابقة\n/declare_winner - إعلان فائز\n/set_rules - تعيين قوانين المجموعة\n/rules - عرض قوانين المجموعة",
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
            "promo_message": "👋 **مرحباً بك في مجموعتنا!**\n\nللاستفادة من جميع خدمات البوت، يرجى التوجه إلى الخاص:\n👉 @{0}\n\nهناك يمكنك إدارة القنوات، ضبط الإعدادات، والمزيد! 🚀",
            "back": "🔙 رجوع"
        },
        'en': {
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
            "help": "❓ **Help**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 **Available Commands:**\n/start - Main Menu\n/trial - Free Trial\n/subscribe - Subscribe\n/syncgroup - Activate Group\n/security - Security Settings\n/register_hidden_owner - Register Hidden Owner\n/add_hidden_admin - Add Hidden Admin\n/remove_hidden_admin - Remove Hidden Admin\n/list_hidden_admins - List Hidden Admins\n/rank - Your Rank\n/top - Top 10\n/stats - Channel Stats\n/lock - Lock Group\n/unlock - Unlock Group\n/schedule - Schedule Post\n/panel - Control Panel\n/language - Change Language\n/support - Support Center\n/help - This Help\n/developer - Developer\n/updates - Updates\n/contests - Contests\n/create_contest - Create Contest\n/declare_winner - Declare Winner\n/set_rules - Set Group Rules\n/rules - View Group Rules",
            "support_welcome": "📞 **Support Center**\n━━━━━━━━━━━━━━━━━━━━━━\nSelect the required service:",
            "support_help": "❓ **Help**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 To contact support:\n• Use /support\n• Write your message\n• You'll get a ticket number\n• We'll reply ASAP\n\n📌 For technical issues:\n• Make sure bot is admin\n• Check bot permissions\n• Review security settings",
            "trial_used": "❌ You have already used the free trial",
            "already_subscribed": "✅ You already have an active subscription",
            "trial": "🎁 **Free Trial Activated!**\n━━━━━━━━━━━━━━━━━━━━━━\n✅ You have 30 days free\n📌 Enjoy all features\n💎 You can subscribe after trial ends",
            "subscribe": "💎 **Subscription**\n━━━━━━━━━━━━━━━━━━━━━━\nChoose your plan:\n\n⭐ 1 Day - 5 Stars\n⭐ 2 Days - 9 Stars\n⭐ 30 Days (Month) - 50 Stars\n⭐ 90 Days (3 Months) - 120 Stars\n\n📌 Payment via Telegram Stars",
            "updates_text": "📢 **Latest Updates**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 Follow updates channel for news:\n• New features\n• Performance improvements\n• Bug fixes\n• Exclusive features",
            "referral_title": "🔗 **Referrals**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 Your referral link:\n`https://t.me/{1}?start=ref_{0}`\n\n👥 Total Referrals: {3}\n🎁 Available Rewards: {4} days\n⭐ Reward per Referral: {5} days\n🎁 Welcome Bonus: {6}",
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
            "subscription_warning": "⚠️ **Warning!**\nYour subscription expires in {0} days\nRenew now to keep features 💎",
            "daily_stats": "📊 **Your Daily Report**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 Channels: {0}\n📝 Total Posts: {1}\n⏳ Unpublished: {2}\n👥 Groups: {3}",
            "weekly_report": "📈 **Your Weekly Report**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 Channels: {0}\n📝 Total Posts: {1}\n⏳ Unpublished: {2}\n👥 Groups: {3}\n🔗 Referrals: {4}",
            "translation_status_off": "Disabled ❌",
            "translation_status_on": "Enabled ✅ to {0}",
            "translation_settings": "Translation Settings",
            "translation_how_it_works": "📌 How it works:\nPosts will be automatically translated to your chosen language when published",
            "translation_choose": "Choose translation language:",
            "translation_off": "🚫 Disable Translation",
            "translation_disabled": "✅ Translation disabled",
            "translation_enabled": "✅ Translation enabled to {0}",
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
            "promo_message": "👋 **Welcome to our group!**\n\nTo use all bot features, please go to private chat:\n👉 @{0}\n\nThere you can manage channels, adjust settings, and more! 🚀",
            "back": "🔙 Back"
        }
    }
    
    for lang, texts in default_langs.items():
        lang_file = LANG_PATH / f"{lang}.json"
        if not lang_file.exists():
            with open(lang_file, 'w', encoding='utf-8') as f:
                json.dump(texts, f, ensure_ascii=False, indent=2)
            print(f"✅ تم إنشاء ملف {lang_file}")

# تحميل اللغات
user_language = {}

def get_text(user_id: int, key: str) -> str:
    """الحصول على نص مترجم من ملف اللغة"""
    lang = user_language.get(user_id, 'ar')
    texts = _lang_data.get(lang, {})
    
    if key not in texts:
        en_texts = _lang_data.get('en', {})
        if key in en_texts:
            return en_texts[key]
    
    return texts.get(key, key)

async def set_user_language(user_id: int, lang: str):
    """تعيين لغة المستخدم"""
    user_language[user_id] = lang

# تحميل اللغات
load_all_languages()

# ===================== متغيرات NSFW =====================
SIGHTENGINE_API_USER = os.getenv("SIGHTENGINE_API_USER", "")
SIGHTENGINE_API_SECRET = os.getenv("SIGHTENGINE_API_SECRET", "")
NSFW_ENABLED = os.getenv("NSFW_ENABLED", "True").lower() in ["true", "1", "yes", "on"]
NSFW_THRESHOLD = float(os.getenv("NSFW_THRESHOLD", "0.7"))
NSFW_MAX_FILE_SIZE = int(os.getenv("NSFW_MAX_FILE_SIZE", 5 * 1024 * 1024))
NSFW_MAX_VIDEO_SIZE = int(os.getenv("NSFW_MAX_VIDEO_SIZE", 10 * 1024 * 1024))
NSFW_FRAMES = int(os.getenv("NSFW_FRAMES", "5"))
NSFW_CACHE = {}
NSFW_CACHE_TTL = 300
_NSFW_CACHE_LOCK = asyncio.Lock()

# ===================== الثوابت =====================
MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', 20 * 1024 * 1024))
MAX_CHANNELS_PER_CYCLE = int(os.getenv('MAX_CHANNELS_PER_CYCLE', '20'))
PUBLISH_RETRY_DELAY = 300
MAX_POSTS_PER_SESSION = 50
MAX_UNPUBLISHED_POSTS = 1000
DB_TIMEOUT = 30
MAX_CONNECTIONS = 20

# ===================== تحسينات اللغة =====================
SUPPORTED_LANGUAGES = {
    'ar': 'العربية 🇸🇦',
    'en': 'English 🇬🇧',
    'fr': 'Français 🇫🇷',
    'tr': 'Türkçe 🇹🇷',
    'zh': '中文 🇨🇳',
    'ru': 'Русский 🇷🇺',
    'de': 'Deutsch 🇩🇪',
    'es': 'Español 🇪🇸',
    'it': 'Italiano 🇮🇹',
    'pt': 'Português 🇵🇹',
    'ja': '日本語 🇯🇵',
    'ko': '한국어 🇰🇷'
}

# ===================== استيراد الكلمات المحظورة من ملف =====================
BANNED_WORDS_FILE = BASE_PATH / "banned_words.txt"
BANNED_PATTERNS = []

def load_banned_words_from_file(file_path: Path) -> List[str]:
    """تحميل الكلمات المحظورة من ملف نصي"""
    words = []
    if not file_path.exists():
        print(f"⚠️ ملف {file_path} غير موجود، سيتم إنشاؤه فارغاً")
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("# قائمة الكلمات المحظورة - كل كلمة في سطر منفصل\n")
                f.write("# ابدأ السطر بـ # للتعليق\n")
                f.write("# استخدم * للتعبيرات النمطية (مثل: سكس.*\n")
                f.write("\n")
                f.write("بورن\n")
                f.write("سكس\n")
                f.write("جنس\n")
                f.write("عري\n")
                f.write("خمر\n")
                f.write("خمور\n")
                f.write("مخدرات\n")
                f.write("حشيش\n")
                f.write("كحول\n")
                f.write("دعارة\n")
            print(f"✅ تم إنشاء ملف {file_path} مع كلمات افتراضية")
        except Exception as e:
            print(f"❌ فشل إنشاء ملف الكلمات المحظورة: {e}")
        return words

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith('#'):
                    continue
                word = line.lower()
                if len(word) >= 2:
                    words.append(word)
                    if '*' in word or '?' in word or '+' in word:
                        try:
                            BANNED_PATTERNS.append(re.compile(word))
                        except:
                            pass
        print(f"✅ تم تحميل {len(words)} كلمة محظورة من {file_path}")
        print(f"✅ تم تحميل {len(BANNED_PATTERNS)} نمط محظور")
    except Exception as e:
        print(f"❌ فشل تحميل الكلمات المحظورة: {e}")

    return words

def import_banned_words_from_file(conn, words: List[str], added_by: int = 1) -> int:
    """استيراد الكلمات المحظورة إلى قاعدة البيانات مع chat_id=-1 (عامة)"""
    if not words:
        return 0
    imported = 0
    try:
        for word in words:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO banned_words (word, chat_id, added_by, added_at) VALUES (?, ?, ?, ?)",
                    (word, -1, added_by, utc_now_iso())
                )
                imported += 1
            except:
                continue
        conn.commit()
        print(f"✅ تم استيراد {imported} كلمة محظورة إلى قاعدة البيانات")
    except Exception as e:
        print(f"❌ فشل استيراد الكلمات المحظورة: {e}")
    return imported

# ===================== نظام كشف NSFW المحسن =====================
async def check_nsfw_cached(image_bytes: bytes, cache_key: str = None) -> dict:
    """التحقق من NSFW مع تخزين مؤقت"""
    if cache_key is None:
        cache_key = hashlib.md5(image_bytes).hexdigest()

    async with _NSFW_CACHE_LOCK:
        if cache_key in NSFW_CACHE:
            cached_data, cached_time = NSFW_CACHE[cache_key]
            if time_module.time() - cached_time < NSFW_CACHE_TTL:
                return cached_data

    result = await check_nsfw_image(image_bytes)

    async with _NSFW_CACHE_LOCK:
        NSFW_CACHE[cache_key] = (result, time_module.time())
        if len(NSFW_CACHE) > 100:
            expired_keys = [k for k, (_, t) in NSFW_CACHE.items() if time_module.time() - t > NSFW_CACHE_TTL]
            for k in expired_keys:
                del NSFW_CACHE[k]

    return result

async def check_nsfw_image(image_bytes: bytes) -> dict:
    """التحقق من صورة إذا كانت غير لائقة باستخدام Sightengine API"""
    try:
        if not SIGHTENGINE_API_USER or not SIGHTENGINE_API_SECRET:
            return {"nsfw": False, "score": 0, "error": "API غير مفعل"}

        img = Image.open(io.BytesIO(image_bytes))
        img.thumbnail((800, 800))
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=80)
        compressed = buffer.getvalue()

        image_b64 = base64.b64encode(compressed).decode('utf-8')

        async with aiohttp.ClientSession() as session:
            url = "https://api.sightengine.com/1.0/check.json"
            params = {
                "models": "nudity-2.0,wad",
                "api_user": SIGHTENGINE_API_USER,
                "api_secret": SIGHTENGINE_API_SECRET,
                "image": image_b64
            }

            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return {"nsfw": False, "score": 0, "error": f"فشل الاتصال ({resp.status})"}

                data = await resp.json()

                nsfw_score = data.get("nudity", {}).get("safe", 1)
                nsfw_score = 1 - nsfw_score

                wad = max(
                    data.get("weapon", 0) or 0,
                    data.get("drugs", 0) or 0,
                    data.get("alcohol", 0) or 0
                )

                faces = data.get("faces", 0) or 0

                return {
                    "nsfw": nsfw_score > NSFW_THRESHOLD or wad > NSFW_THRESHOLD,
                    "nsfw_score": round(nsfw_score, 2),
                    "wad_score": round(wad, 2),
                    "faces": faces,
                    "safe_score": round(1 - nsfw_score, 2),
                    "raw": data
                }

    except Exception as e:
        logger.error(f"خطأ في كشف NSFW للصورة: {e}")
        return {"nsfw": False, "score": 0, "error": str(e)}

async def check_nsfw_video(video_bytes: bytes, frames: int = NSFW_FRAMES) -> dict:
    """التحقق من فيديو عن طريق أخذ عينات من الإطارات"""
    if not CV2_AVAILABLE:
        return {"nsfw": False, "score": 0, "error": "cv2 غير مثبت"}

    try:
        if not video_bytes:
            return {"nsfw": False, "score": 0, "error": "فيديو فارغ"}

        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        cap = cv2.VideoCapture(tmp_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if total_frames == 0:
            cap.release()
            os.unlink(tmp_path)
            return {"nsfw": False, "score": 0, "error": "لا يمكن قراءة الفيديو"}

        frame_indices = np.linspace(0, total_frames - 1, min(frames, total_frames), dtype=int)
        nsfw_scores = []
        wad_scores = []
        faces_count = 0

        for idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue

            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            img_bytes = buffer.tobytes()

            result = await check_nsfw_image(img_bytes)
            if not result.get("error"):
                nsfw_scores.append(result.get("nsfw_score", 0))
                wad_scores.append(result.get("wad_score", 0))
                faces_count += result.get("faces", 0)

            await asyncio.sleep(0.1)

        cap.release()
        os.unlink(tmp_path)

        if not nsfw_scores:
            return {"nsfw": False, "score": 0, "error": "لا يمكن تحليل الإطارات"}

        avg_nsfw = sum(nsfw_scores) / len(nsfw_scores)
        avg_wad = sum(wad_scores) / len(wad_scores)

        return {
            "nsfw": avg_nsfw > NSFW_THRESHOLD or avg_wad > NSFW_THRESHOLD,
            "nsfw_score": round(avg_nsfw, 2),
            "wad_score": round(avg_wad, 2),
            "faces": faces_count // len(frame_indices) if frame_indices else 0,
            "frames_analyzed": len(nsfw_scores),
            "max_nsfw_score": round(max(nsfw_scores), 2) if nsfw_scores else 0,
            "max_wad_score": round(max(wad_scores), 2) if wad_scores else 0
        }

    except Exception as e:
        logger.error(f"خطأ في كشف NSFW للفيديو: {e}")
        return {"nsfw": False, "score": 0, "error": str(e)}

# ===================== 200 رد تلقائي للمجموعات =====================
WELCOME_REPLIES = {
    "مرحباً": ["أهلاً وسهلاً بك في مجموعتنا 🤍", "أهلاً بك، نورت المجموعة 🌸", "مرحباً، تشرفنا بوجودك 🙏"],
    "السلام عليكم": ["وعليكم السلام ورحمة الله وبركاته 🌹", "وعليكم السلام، نورت المجموعة 🌸", "الله يبارك فيك 🙏"],
    "اهلاً": ["أهلاً بك، تشرفنا 🙏", "أهلاً وسهلاً 🌹", "نورتنا يا غالي 🌸"],
    "هلا": ["هلا والله، نورت المجموعة ✨", "هلا بك مليون 🌹", "هلا هلا، تشرفنا 🙏"],
    "مرحبا بكم": ["أهلاً بكم جميعاً، تشرفنا بتواجدكم 🌸", "نورتونا جميعاً 🌹", "أهلاً وسهلاً بالجميع 🙏"],
    "هلا والله": ["هلا بك، نورت الدنيا 🌹", "هلا والله، تشرفنا 🌸", "نورت يا غالي ✨"],
    "مرحبا مليون": ["مليون مرحبة، نورت ✨", "مرحبا مليون، تشرفنا 🌹", "نورت الدنيا يا حلو 🌸"],
    "اهلا وسهلا": ["أهلاً وسهلاً، حياك الله 🙏", "أهلاً وسهلاً، نورتنا 🌹", "حياك الله وبياك 🌸"],
    "نورت": ["نورت المجموعة بوجودك 🌸", "نورت الدنيا ياحلو 🌹", "نورتنا جميعاً ✨"],
    "شرفت": ["شرفتنا يا غالي 🌹", "شرفت الدنيا بوجودك 🌸", "تشرفنا بمعرفتك 🙏"],
    "تشرفنا": ["تشرفنا بمعرفتك 🙏", "الشرف لنا 🌹", "نورتنا بوجودك 🌸"],
    "منور": ["منور الدنيا يا حلو 🌸", "منور أنت ياغالي 🌹", "نورت المجموعة ✨"],
    "ياهلا": ["ياهلا بك مليون 🌹", "ياهلا وسهلا 🌸", "نورت يا غالي 🙏"],
    "اهلين": ["أهلين وسهلين ✨", "أهلين بك 🌹", "حياك الله 🌸"],
    "مسا الخير": ["مسا النور 🌙", "مسا الخير، نورتنا 🌹", "مسا العسل 🌸"],
    "صباح الخير": ["صباح النور 🌞", "صباح الخير، نورت اليوم 🌹", "صباح الورد 🌸"],
    "تصبح على خير": ["وأنت من أهله 🌙", "تصبح على خير ورضا 🌹", "الله يسلمك 🌸"],
    "مساء النور": ["أهلين وسهلين 🌸", "مساء النور والسرور 🌹", "حياك الله 🙏"],
    "نورت الدنيا": ["أنت النور 🌹", "نورت العالم بوجودك 🌸", "الدنيا بنورك ✨"],
    "فرحتنا": ["فرحتنا بوجودك 🤍", "نورت فرحتنا 🌹", "فرحة بمعرفتك 🌸"]
}

FAQ_REPLIES = {
    "كيف حالك": ["الحمد لله، بخير وأنت؟ ❤️", "بخير، تسلم 🌹", "الحمد لله، كيفك أنت؟ 🌸"],
    "شو اخبارك": ["كل الخير، كيفك أنت؟ 🌹", "بخير الحمد لله ❤️", "الخبر كله خير 🌸"],
    "اخبارك": ["بخير، الحمد لله 🙏", "تمام، الحمد لله 🌹", "بخير، تسلم 🌸"],
    "شنو اخبارك": ["الحمد لله، كيفك أنت؟ ❤️", "كل تمام، كيفك؟ 🌹", "بخير الحمد لله 🌸"],
    "شخبارك": ["شخبارك أنت؟ 🌸", "بخير، تسلم 🌹", "الحمد لله، وأنت؟ 🙏"],
    "وينكم": ["هني موجودين، شنو المطلوب؟ 👋", "أنا هنا، تحت أمرك 🌹", "هني ننتظرك 🌸"],
    "وينك": ["أنا هنا، شنو تحتاج؟ 🤖", "هني موجود، تفضل 🌹", "تحت أمرك 🙏"],
    "شنو اسمك": ["أنا البوت، تحت أمرك 🙏", "اسمي البوت، تشرفنا 🤖", "أنا مساعد المجموعة 🌸"],
    "وش اسمك": ["أنا البوت، تشرفنا 🤖", "اسمي البوت، سعيد بمعرفتك 🌹", "أنا ريلاكس مانيجر 🙏"],
    "منو انت": ["أنا البوت، مساعد المجموعة 🛡️", "أنا مدير المجموعة 🤖", "أنا خادمكم 🙏"],
    "ايش اسمك": ["اسمي البوت، سعيد بمعرفتك 🌹", "أنا البوت، تحت أمرك 🙏", "ريلآكس مانيجر 🤖"],
    "كيفك انت": ["بخير الحمد لله 🌸", "تمام، كيفك أنت؟ 🌹", "الحمد لله، تسلم 🙏"],
    "وشلونك": ["الحمد لله، كيفك أنت؟ ❤️", "تمام، الحمد لله 🌹", "بخير، تسلم 🌸"],
    "كيف الأحوال": ["كل تمام، الحمد لله 🙏", "الأحوال بخير 🌹", "الحمد لله على كل حال 🌸"],
    "شو وضعك": ["تمام، الحمد لله 🌹", "بخير، تسلم 🙏", "الحمد لله، كيفك؟ 🌸"],
    "كيف الحال": ["الحال دوماً بخير 🌸", "بخير، الحمد لله 🌹", "الحال كله تمام 🙏"],
    "ايش اخبارك": ["الخبر كله خير ❤️", "كل الخير، تسلم 🌹", "أخبار طيبة 🌸"],
    "اخبار الدنيا": ["الدنيا بخير 🌹", "الحمد لله، الدنيا تمام 🌸", "كل شيء بخير 🙏"],
    "شو جديد": ["الجديد هو وجودك معنا ✨", "كل يوم جديد معكم 🌹", "الجديد فرحتنا بكم 🌸"],
    "ايش جديدك": ["جديدك يفرحنا 🌸", "أخبارك تسعدنا 🌹", "كل جديدك حلو ✨"],
    "كيف اليوم": ["اليوم جميل بحضورك 🌹", "يومك يبدأ بالخير 🌸", "اليوم ممتع معكم 🙏"],
    "شو تسوي": ["أساعد الناس، وهني بانتظارك 🤖", "أخدمكم وأدير المجموعة 🌹", "بخدمتكم 🙏"],
    "اين انت": ["أنا هنا، تحت أمرك 🙏", "هني موجود، تفضل 🌹", "أنا معكم دائماً 🌸"],
    "شنو تسوي": ["أخدم المجموعة وأديرها 📡", "أساعد في الإدارة 🌹", "أنا هنا لخدمتكم 🙏"],
    "ماذا تفعل": ["أساعد في إدارة المجموعة 🛡️", "أنشر وأحمي 🌹", "أخدم المجموعة 🙏"]
}

POSITIVE_REPLIES = {
    "شكراً": ["العفو، تحت أمرك دائماً ❤️", "العفو، أهلين 🙏", "الشكر لله 🌹"],
    "شكرا": ["العفو، أهلين 🙏", "العفو، نورت 🌸", "تسلم يا غالي 🌹"],
    "تسلم": ["تسلم يا غالي 🌸", "تسلم يدك 🌹", "الله يسلمك 🙏"],
    "تسلمي": ["تسلمي يا غالية 🌹", "تسلم يدك 🌸", "الله يسلمك 🙏"],
    "يسلمو": ["يسلم قلبك ❤️", "يسلمو على الذوق 🌹", "الله يسلمك 🌸"],
    "يعطيك العافية": ["يعافيك ربي ❤️", "الله يعافيك 🌹", "تسلم، يعافيك 🌸"],
    "يعطيك الف عافية": ["الله يعافيك 🌹", "يعافيك ربي 🙏", "تسلم يا غالي 🌸"],
    "ربي يوفقك": ["وإياك يا رب 🌸", "الله يوفق الجميع 🌹", "آمين يا رب 🙏"],
    "جزاك الله خير": ["وإياكم، الله يبارك فيك 🌹", "آمين، الله يجزاك خير 🌸", "الله يبارك فيك 🙏"],
    "الف شكر": ["ألف شكر لك 🙏", "الشكر لله 🌹", "تسلم على الذوق 🌸"],
    "مشكور": ["مشكور يا غالي 🌸", "العفو 🌹", "تسلم 🙏"],
    "مشكورة": ["مشكورة يا غالية 🌹", "العفو 🌸", "تسلمي 🙏"],
    "شكراً جزيلاً": ["الشكر لله ثم لك ❤️", "العفو، أهلين 🌹", "تسلم على كلامك 🌸"],
    "يعطيك الصحة": ["الله يعافيك 🙏", "يعطيك الصحة والعافية 🌹", "تسلم 🌸"],
    "ربي يعطيك العافية": ["يعافيك ربي 🌹", "الله يعافيك 🙏", "تسلم 🌸"],
    "ممتاز": ["شكراً لك 🌟", "أشكرك 🌹", "ممتاز أنت 🌸"],
    "رائع": ["يعجبني هذا 🌸", "روعة 🌹", "شكراً 🙏"],
    "جميل": ["روعة 🌹", "جميل جداً 🌸", "أشكرك 🙏"],
    "الله يبارك فيك": ["وفيك بارك الله 🙏", "آمين، وبارك فيك 🌹", "الله يبارك في الجميع 🌸"],
    "تقبل مروري": ["نورتنا بمرورك 🌸", "شكراً لمرورك 🌹", "تشرفنا بوجودك 🙏"]
}

RELIGIOUS_REPLIES = {
    "ما شاء الله": ["تبارك الرحمن 🤍", "ما شاء الله تبارك الله 🌹", "الله يبارك 🙏"],
    "ماشاءالله": ["تبارك الله 🌹", "الله يبارك فيك 🙏", "ما شاء الله 🌸"],
    "ما شاء الله تبارك الله": ["الله يبارك فيك 🙏", "تبارك الرحمن 🌹", "ما شاء الله 🌸"],
    "الحمد لله": ["الحمد لله دائماً وأبداً 🙏", "الحمد لله على كل حال 🌹", "الحمد لله رب العالمين 🌸"],
    "سبحان الله": ["سبحان الله وبحمده 🌹", "سبحان الله العظيم 🙏", "سبحان الله وبحمده 🌸"],
    "سبحان الله وبحمده": ["سبحان الله العظيم 🌸", "سبحان الله وبحمده 🙏", "سبحان الله 🌹"],
    "اللهم صل على محمد": ["اللهم صل وسلم وبارك على نبينا محمد 🌸", "اللهم صل على محمد وآل محمد 🌹", "اللهم صل على سيدنا محمد 🙏"],
    "صل على النبي": ["اللهم صل على محمد 🌹", "اللهم صل وسلم وبارك عليه 🌸", "اللهم صل على سيدنا محمد 🙏"],
    "استغفر الله": ["ربي اغفر لي ولوالديّ 🙏", "أستغفر الله العظيم 🌹", "اللهم اغفر لي 🌸"],
    "استغفر الله العظيم": ["الله أكبر، أستغفرك وأتوب إليك 🤍", "أستغفر الله العظيم الذي لا إله إلا هو 🌹", "ربي اغفر لي 🙏"],
    "لا اله الا الله": ["لا إله إلا الله محمد رسول الله 🙏", "لا إله إلا الله وحده لا شريك له 🌹", "شهادة الحق 🌸"],
    "الله اكبر": ["الله أكبر كبيراً 🌹", "الله أكبر، الحمد لله 🙏", "الله أكبر وأعلى 🌸"],
    "الحمدلله": ["الحمد لله رب العالمين 🙏", "الحمد لله على كل حال 🌹", "الحمد لله دائماً 🌸"],
    "ربي": ["لبيك يا رب 🌸", "ربي معي 🌹", "ربي كريم 🙏"],
    "اللهم": ["آمين يا رب العالمين 🤍", "اللهم استجب 🙏", "اللهم لك الحمد 🌹"],
    "سبحانه": ["سبحانه وتعالى 🙏", "سبحان الله العظيم 🌹", "سبحانه وتقدس 🌸"],
    "تعالى الله": ["الله أعلى وأعلم 🌹", "تعالى الله عما يشركون 🙏", "الله أعلى 🌸"],
    "بسم الله": ["بسم الله الرحمن الرحيم 🤍", "بسم الله توكلت على الله 🙏", "بسم الله ما شاء الله 🌹"],
    "توكلت على الله": ["حسبي الله ونعم الوكيل 🙏", "توكلت على الله الحي القيوم 🌹", "الله كافي 🌸"],
    "رب العالمين": ["رب السماوات والأرض 🌹", "رب العالمين أجمعين 🙏", "الله رب العالمين 🌸"],
    "الرحمن": ["بسم الله الرحمن الرحيم 🤍", "الرحمن الرحيم 🙏", "الله الرحمن 🌹"],
    "الرحيم": ["الرحيم بعباده 🙏", "الرحمن الرحيم 🌹", "الله الرحيم 🌸"],
    "الملك": ["الملك القدوس 🌹", "الملك الحق المبين 🙏", "الله الملك 🌸"],
    "القدوس": ["سبحان القدوس 🤍", "القدوس السلام 🙏", "سبحان الله القدوس 🌹"],
    "السلام": ["السلام عليكم ورحمة الله 🌸", "السلام عليكم 🙏", "السلام عليكم ورحمة الله وبركاته 🌹"]
}

JOKE_REPLIES = {
    "ضحك": ["😂😂", "ههههه 🤣", "ضحكتني 😂"],
    "نكتة": ["مرة واحد قال للبوت: وينك؟ قال البوت: هني 👻", "مرة واحد سأل البوت: أيش تسوي؟ قال: أنشر وأحمي 🤖", "نكتة جديدة: البوت يقول للمستخدم: أنت نورت 🌟"],
    "مزح": ["😅😅", "ههههه 🤣", "مزح مزح 😂"],
    "فكة": ["😂🤣", "هههههه 🤣", "فكة عسل 😂"],
    "وناسة": ["🤩🤩", "وناسة يا جماعة 🌸", "جو وناسة 😊"],
    "طقطقة": ["😂😂", "طق طق 🤣", "ههههه طقطقة حلوة 😂"],
    "خبلت": ["هههههه 🤣", "خبلتني 😂", "ههههه خبل 🤣"],
    "هههه": ["😂🤣", "هههههه 🤣", "ضحكتني 😂"],
    "ضحكتني": ["أنا مبسوط إنك ضحكت 😊", "😊😊", "أنا سعيد بإضحاكك 🌹"],
    "ههههههه": ["ههههههههه 🤣😂", "هههههه 🤣", "موتني ضحك 😂"],
    "ضحكك": ["يضحكني حضورك 😂", "ضحكك حلو 🌸", "أضحكني 😊"],
    "نكتة جديدة": ["مرة وحدة سألت البوت: أيش تسوي؟ قال: أنشر وأحمي 🤖", "نكتة: البوت مشغول بالنشر 😂", "مرة البوت قال للمستخدم: أنت الغالي 🌹"],
    "طشة": ["😂😂", "طشة عسل 😂", "ههههه 🤣"],
    "مموت": ["ههههه، ضحكتني 🤣", "موتني ضحك 😂", "ههههه 🤣"],
    "قهقهة": ["ههههههههه 😂", "قهقهة حلوة 🤣", "هههههه 😊"],
    "ضحك عالي": ["ههههههههههه 🤣", "ضحك عالي جداً 😂", "ههههههه 🤣"],
    "نكتة حلوة": ["أحلى نكتة هي وجودك معنا 😊", "نكتة حلوة منك 🌸", "أحلى نكتة 🌹"],
    "وناسة": ["جو وناسة 🤩", "وناسة يا جماعة 😊", "جو جميل 🌸"],
    "اخبارك": ["تضحك وتبسط 😂", "أخبارك طيبة 🌹", "كل الخير 🙏"],
    "طقطقة حلوة": ["هههه، طق طق 🤣", "طقطقة عسل 😂", "ههههه طقطقة حلوة 🌸"],
    "فكه": ["فكة عسل 😂", "فكة وناسة 🤣", "ههههه فكه 🌸"],
    "خوش واحد": ["ههههه 🤣", "خوش واحد أنت 🌹", "ضحكتني 😂"],
    "موتني": ["موتني ضحك 😂", "ههههه موتني 🤣", "ما رح أموت ضحك 😊"],
    "نكتة اليوم": ["اليوم يومك 😊", "نكتة اليوم من عندك 🌹", "اليوم يوم سعيد 🌸"],
    "حلوة": ["حلوتك 🤩", "حلوة منك 🌹", "أجمل نكتة 🌸"],
    "ايش هالضحك": ["ضحكك يفرحني 😂", "ضحك حلو 🌸", "أنا مبسوط 🌹"],
    "يهبل": ["ههههه 🤣", "يهبل ضحك 😂", "ههههه يهبل 🌸"],
    "يكسر": ["ههههههه 🤣😂", "يكسر القلب 😂", "ههههه يكسّر 🌹"],
    "مزة": ["ههههه 🤣", "مزة منك 🌸", "ههههه مزة 😂"],
    "جو": ["جو حلو 😊", "جو رائع 🌹", "جو ممتع 🌸"]
}

MOTIVATIONAL_REPLIES = {
    "تعبت": ["إرتاح شوي، تستاهل الراحة 😊", "خذ قسط من الراحة 🌸", "تستاهل كل خير 🙏"],
    "زعلان": ["لا تزعل، كل شيء بيصير خير ❤️", "الدنيا جميلة، ابتسم 🌹", "كل شيء سيكون بخير 🌸"],
    "فرحان": ["الله يفرح قلبك 😊", "فرحتنا بفرحك 🌹", "تبقى مبسوط دائماً 🌸"],
    "ناجح": ["ألف مبروك، تستاهل كل خير 🎉", "مبروك النجاح 🌹", "أنت ناجح دائماً 🙏"],
    "فائز": ["مبروك الفوز، أنت تستاهل 🏆", "ألف مبروك 🌹", "أنت فائز دائماً 🌸"],
    "متعب": ["خذ قسط من الراحة 🌸", "إرتاح شوي، راح ترتاح 🌹", "تستاهل الراحة 🙏"],
    "محبط": ["لا تحبط، النجاح قريب 💪", "الدنيا بخير، ابتسم 🌹", "أنت أقوى من ذلك 🌸"],
    "متفائل": ["تفاؤلك خير 🌹", "التفاؤل طريق النجاح 🌸", "أنت متفائل دائماً 🙏"],
    "حزين": ["كل شيء سيكون بخير ❤️", "لا تحزن، الله معك 🌹", "الحياة جميلة 🌸"],
    "مبسوط": ["أجمل شعور هو السعادة 😊", "سعادتك تسعدني 🌹", "تبقى مبسوط دائماً 🌸"],
    "متحمس": ["حماسك جميل 🔥", "استمر بالحماس 🌹", "أنت متحمس دائماً 🙏"],
    "مبدع": ["إبداعك رائع 🌟", "أنت مبدع دائماً 🌹", "إبداعك يفرحنا 🌸"],
    "متطور": ["أنت تتطور باستمرار 🚀", "التطور طريق النجاح 🌹", "أنت في تطور مستمر 🙏"],
    "طموح": ["طموحك يوصلك للنجاح 💫", "الطموح طريق القمة 🌹", "أنت طموح دائماً 🌸"],
    "ناجح": ["أنت ناجح دائماً 🎉", "النجاح حليفك 🌹", "مبروك النجاح 🙏"]
}

SOCIAL_REPLIES = {
    "كيفك": ["بخير الحمد لله، وأنت؟ 🌹", "بخير، تسلم ❤️", "الحمد لله، كيفك أنت؟ 🌸"],
    "كيفك انت": ["بخير، تسلم ❤️", "بخير، الحمد لله 🌹", "أنا بخير، شكراً 🙏"],
    "اخبار العائلة": ["كلهم بخير، الحمد لله 🙏", "العائلة بخير 🌹", "الحمد لله على كل حال 🌸"],
    "والديك": ["بخير، الحمد لله 🌸", "والديك في أفضل حال 🌹", "الله يحفظهم 🙏"],
    "الاهل": ["الحمد لله، كلهم بخير 🌹", "الأهل في خير 🌸", "الله يحفظ العائلة 🙏"],
    "الصحة": ["الحمد لله على كل حال 🙏", "الصحة نعمة 🌹", "الحمد لله، بخير 🌸"],
    "العمل": ["الحمد لله، أموره طيبة 🌸", "العمل بخير 🌹", "الحمد لله على كل حال 🙏"],
    "الدراسة": ["بالتوفيق إن شاء الله 📚", "الله يوفقك 🌹", "النجاح حليفك 🌸"],
    "الجامعة": ["الله يوفقك يارب 🌹", "الجامعة تنتظر نجاحك 🌸", "بالتوفيق 🙏"],
    "المدرسة": ["بالتوفيق والنجاح 🌸", "المدرسة تنتظرك 🌹", "الله يوفقك 🙏"],
    "البيت": ["الحمد لله، بيتنا بخير 🙏", "البيت جميل 🌹", "الحمد لله 🌸"],
    "السفر": ["الله يسهل لك 🌹", "سفر مبارك 🌸", "الله يحفظك 🙏"],
    "السيارة": ["سلامتك يا رب 🚗", "السيارة بخير 🌹", "الحمد لله 🌸"],
    "السكن": ["الحمد لله، مستقرين 🌸", "السكن بخير 🌹", "الحمد لله 🙏"],
    "المال": ["الحمد لله، رزق حلال 🙏", "المال يزيد بالبركة 🌹", "الحمد لله 🌸"],
    "الزواج": ["الله يبارك لك 🌹", "ألف مبروك 🌸", "الله يتمم بخير 🙏"],
    "العزوبية": ["الله يرزقك الزوجة الصالحة 🙏", "الزواج نصيب 🌹", "الله يكتب الخير 🌸"],
    "الأولاد": ["الله يبارك لك فيهم 🌸", "الأولاد زينة الحياة 🌹", "الله يحفظهم 🙏"],
    "البنات": ["الله يحفظهم لك 🌹", "البنات نعمة 🌸", "الله يرعاهم 🙏"],
    "العائلة": ["الله يجمع شملكم 🤍", "العائلة أغلى ما نملك 🌹", "الله يحمي العائلة 🌸"]
}

ADMIN_REPLIES = {
    "ممنوع": ["تم التنبيه، يرجى احترام قوانين المجموعة 🚫", "ممنوع، يرجى الالتزام 🌹", "تنبيه: ممنوع 🙏"],
    "انتبه": ["رجاءً انتبه للقوانين ⚠️", "انتبه يا غالي 🌹", "تنبيه مهم 🌸"],
    "قوانين": ["قوانين المجموعة موجودة في الوصف 📋", "اقرأ القوانين في الوصف 🌹", "القوانين واضحة 🙏"],
    "مخالفة": ["تنبيه: هذا مخالف للقوانين 🚫", "مخالفة، يرجى الانتباه 🌹", "تنبيه مهم 🌸"],
    "تحذير": ["تحذير أول، يرجى الالتزام بالقوانين ⚠️", "تحذير، انتبه 🌹", "هذا تحذير 🙏"],
    "طرد": ["سيتم تطبيق العقوبات 🚫", "طرد، انتبه 🌹", "عقوبات رادعة 🌸"],
    "حظر": ["تم حظر المخالف 🚫", "حظر، انتبه 🌹", "تم تطبيق الحظر 🙏"],
    "كتم": ["تم كتم المخالف 🔇", "كتم لمدة محددة 🌹", "تم تطبيق الكتم 🌸"],
    "سجل": ["تم تسجيل المخالفة 📝", "سجل المخالفات 🌹", "تم التوثيق 🙏"],
    "تنبيه": ["تنبيه هام يرجى قراءة القوانين 📋", "تنبيه للمخالفين 🌹", "انتبه للقوانين 🌸"]
}

REQUEST_REPLIES = {
    "بليز": ["حاضر، بس أرسل طلبك بالتفصيل 📝", "تفضل، أنا هنا 🌹", "أرسل طلبك 🙏"],
    "من فضلك": ["تفضل، أنا هنا للمساعدة 🤖", "تفضل، بكامل الخدمة 🌹", "أنا في خدمتك 🌸"],
    "تكرم": ["أمرك يا غالي 🌹", "تفضل، أنا هنا 🙏", "بكامل الخدمة 🌸"],
    "لو سمحت": ["تفضل، أنا جاهز 🙏", "تفضل، بكامل الخدمة 🌹", "أنا في انتظارك 🌸"],
    "عندي طلب": ["أرسل طلبك وسأساعدك 💡", "تفضل بطلبك 🌹", "أنا في الخدمة 🙏"],
    "طلب": ["تفضل بطلبك 📝", "أرسل طلبك 🌹", "أنا هنا لمساعدتك 🌸"],
    "سؤال": ["اسأل، وأنا هنا للإجابة ❓", "تفضل بسؤالك 🌹", "أنا هنا للإجابة 🙏"],
    "استفسار": ["تفضل بالاستفسار 📋", "أنا هنا للإجابة 🌹", "تفضل 🌸"],
    "مساعدة": ["كيف أقدر أساعدك؟ 🤖", "أنا هنا لمساعدتك 🌹", "تفضل، أنا في الخدمة 🙏"],
    "دعم": ["أنا هنا لدعمك 💪", "الدعم متوفر 🌹", "نحن معك 🙏"],
    "شكوى": ["اشرح شكوتك وسنحلها 📞", "تفضل بشكوتك 🌹", "نحن هنا لحلها 🌸"],
    "مشكلة": ["اشرح مشكلتك، سأحاول مساعدتك 💡", "تفضل بمشكلتك 🌹", "نحن هنا لحلها 🙏"],
    "اقتراح": ["تفضل باقتراحك، نرحب بكل فكرة 💡", "اقتراحك يهمنا 🌹", "تفضل بفكرتك 🌸"],
    "فكرة": ["شاركنا فكرتك الجميلة 🌟", "فكرتك تهمنا 🌹", "تفضل بفكرتك 🙏"],
    "رأي": ["نرحب برأيك القيم 📝", "رأيك يهمنا 🌹", "تفضل برأيك 🌸"]
}

ABOUT_BOT_REPLIES = {
    "مين انت": ["أنا البوت، مساعد لإدارة المجموعات 🤖", "أنا ريلاكس مانيجر 🌹", "أنا خادم المجموعة 🙏"],
    "ايش تسوي": ["أساعد في إدارة المجموعات، النشر، الأمان، والكثير 📋", "أدير القنوات والمجموعات 🌹", "أنا مساعد شامل 🌸"],
    "مهمتك": ["تنظيم المجموعات وحمايتها من المزعجين 🛡️", "الأمان أولاً 🌹", "حماية المجموعة 🙏"],
    "شغلك": ["أنشر المنشورات، أحافظ على الأمان، وأدير القنوات 📡", "إدارة متكاملة 🌹", "خدمة المجموعة 🌸"],
    "ايش تقدر": ["أقدر أساعدك في إدارة القناة والمجموعة 💪", "كل شيء تقريباً 🌹", "أنا متعدد المهام 🙏"],
    "مهاراتك": ["النشر التلقائي، الأمان، الردود، والإحصائيات 📊", "مهارات متعددة 🌹", "أنا شامل 🌸"],
    "شو اختصاصك": ["إدارة القنوات والمجموعات بكل احترافية 🎯", "اختصاصي الإدارة 🌹", "الخدمة المتكاملة 🙏"],
    "ليش انت هنا": ["لأخدمكم وأساعد في تنظيم المجموعة 🌸", "أنا هنا لخدمتكم 🌹", "لأدير المجموعة 🙏"],
    "عرف نفسك": ["أنا بوت مساعد، تحت أمركم 🙏", "أنا ريلاكس مانيجر 🌹", "أنا خادمكم 🌸"],
    "شنو فائدتك": ["أسهل عليك إدارة القناة والمجموعة 🚀", "فائدتي في الخدمة 🌹", "أنا هنا لمساعدتك 🙏"]
}

EXTRA_REPLIES = {
    "تمام": ["تمام يا غالي 🌸", "تمام، تسلم 🌹", "أوكي 🙏"],
    "اوك": ["أوكي، تحت أمرك 🙏", "أوكي، تمام 🌹", "ممتاز 🌸"],
    "حاضر": ["حاضر، أنا جاهز 💪", "حاضر، تفضل 🌹", "تحت أمرك 🙏"],
    "ان شاء الله": ["إن شاء الله خير 🌹", "إن شاء الله 🌸", "بإذن الله 🙏"],
    "باذن الله": ["بإذن الله 🙏", "بإذن الله خير 🌹", "إن شاء الله 🌸"],
    "مع السلامة": ["مع السلامة، تشرفنا بك 🌸", "مع السلامة 🌹", "أهلاً وسهلاً بك 🙏"],
    "باي": ["باي، نورت 🌹", "مع السلامة 🌸", "تشرفنا بك 🙏"],
    "سلام": ["سلام، الله يحفظك 🙏", "سلام عليكم 🌹", "مع السلامة 🌸"],
    "ياعيني": ["ياعيني عليك 🌹", "ياعيني، أنت الغالي 🌸", "ياعيني يا حلو 🙏"],
    "ياحلو": ["حلوك الله 🌸", "أنت الحلو 🌹", "حلو كلامك 🙏"]
}

# ===== نظام الردود المتعددة =====
REPLY_WEIGHTS = {
    'welcome': [0.5, 0.3, 0.2],
    'faq': [0.4, 0.3, 0.3],
    'positive': [0.4, 0.4, 0.2],
    'religious': [0.4, 0.3, 0.3],
    'joke': [0.3, 0.4, 0.3],
    'motivational': [0.4, 0.3, 0.3],
    'social': [0.4, 0.3, 0.3],
    'admin': [0.5, 0.3, 0.2],
    'request': [0.4, 0.3, 0.3],
    'about': [0.4, 0.3, 0.3],
    'extra': [0.4, 0.3, 0.3]
}

def get_weighted_reply(reply_list: List[str], category: str = 'default') -> str:
    """اختيار رد عشوائي من القائمة مع الأوزان"""
    if not reply_list:
        return "🙏"
    if len(reply_list) == 1:
        return reply_list[0]

    weights = REPLY_WEIGHTS.get(category, [0.4, 0.3, 0.3])
    weights = weights[:len(reply_list)]
    if len(weights) < len(reply_list):
        weights.extend([0.1] * (len(reply_list) - len(weights)))
    total = sum(weights)
    weights = [w / total for w in weights]
    return random.choices(reply_list, weights=weights, k=1)[0]

# ===== دمج الردود =====
ALL_REPLIES = {}
ALL_REPLIES.update({k: get_weighted_reply(v, 'welcome') if isinstance(v, list) else v for k, v in WELCOME_REPLIES.items()})
ALL_REPLIES.update({k: get_weighted_reply(v, 'faq') if isinstance(v, list) else v for k, v in FAQ_REPLIES.items()})
ALL_REPLIES.update({k: get_weighted_reply(v, 'positive') if isinstance(v, list) else v for k, v in POSITIVE_REPLIES.items()})
ALL_REPLIES.update({k: get_weighted_reply(v, 'religious') if isinstance(v, list) else v for k, v in RELIGIOUS_REPLIES.items()})
ALL_REPLIES.update({k: get_weighted_reply(v, 'joke') if isinstance(v, list) else v for k, v in JOKE_REPLIES.items()})
ALL_REPLIES.update({k: get_weighted_reply(v, 'motivational') if isinstance(v, list) else v for k, v in MOTIVATIONAL_REPLIES.items()})
ALL_REPLIES.update({k: get_weighted_reply(v, 'social') if isinstance(v, list) else v for k, v in SOCIAL_REPLIES.items()})
ALL_REPLIES.update({k: get_weighted_reply(v, 'admin') if isinstance(v, list) else v for k, v in ADMIN_REPLIES.items()})
ALL_REPLIES.update({k: get_weighted_reply(v, 'request') if isinstance(v, list) else v for k, v in REQUEST_REPLIES.items()})
ALL_REPLIES.update({k: get_weighted_reply(v, 'about') if isinstance(v, list) else v for k, v in ABOUT_BOT_REPLIES.items()})
ALL_REPLIES.update({k: get_weighted_reply(v, 'extra') if isinstance(v, list) else v for k, v in EXTRA_REPLIES.items()})

# ===== تحميل ملفات البيئة =====
def load_env_files():
    from dotenv import load_dotenv
    env_files = [
        ".env",
        ".env.local",
        str(BASE_PATH / ".env"),
        str(BASE_PATH / "config" / ".env"),
        str(Path.home() / ".bot" / ".env"),
    ]
    for env_file in env_files:
        if os.path.exists(env_file):
            load_dotenv(env_file)
            return True
    return False

load_env_files()

def get_env_or_default(key: str, default: any, env_type: type = str) -> any:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        if env_type == bool:
            return value.lower() in ['true', '1', 'yes', 'on']
        elif env_type == int:
            return int(value)
        elif env_type == float:
            return float(value)
        return env_type(value)
    except:
        return default

# ===================== الثوابت =====================
TOKEN = get_env_or_default("BOT_TOKEN", None, str)
if not TOKEN:
    raise ValueError("❌ لم يتم العثور على BOT_TOKEN في ملفات البيئة")

PRIMARY_OWNER_ID = get_env_or_default("MAIN_ADMIN_ID", 0, int)
if PRIMARY_OWNER_ID == 0:
    raise ValueError("❌ MAIN_ADMIN_ID غير محدد في ملفات البيئة")

BOT_NAME = get_env_or_default("BOT_NAME", "ريلاكس مانيجر", str)
BOT_USERNAME = get_env_or_default("BOT_USERNAME", "Reelaaaxbot", str)
USE_PROXY = get_env_or_default("USE_PROXY", False, bool)
PROXY_URL = get_env_or_default("PROXY_URL", "http://127.0.0.1:10809", str)
ENABLE_2FA = get_env_or_default("ENABLE_2FA", False, bool)
ADMIN_2FA_SECRET = get_env_or_default("ADMIN_2FA_SECRET", "", str)
DB_ENCRYPTION = get_env_or_default("DB_ENCRYPTION", True, bool)
MAX_BACKUPS = get_env_or_default("MAX_BACKUPS", 10, int)
SECURITY_LOG_LEVEL = get_env_or_default("SECURITY_LOG_LEVEL", "CRITICAL", str)

GOOGLE_DRIVE_FOLDER_ID = get_env_or_default("GOOGLE_DRIVE_FOLDER_ID", "", str)
CLOUD_BACKUP_ENABLED = get_env_or_default("CLOUD_BACKUP_ENABLED", False, bool) and GOOGLE_AUTH_AVAILABLE
GOOGLE_CREDENTIALS_FILE = get_env_or_default("GOOGLE_CREDENTIALS_FILE", "credentials.json", str)
TOKEN_FILE = get_env_or_default("TOKEN_FILE", "token.json", str)

# ===== إعدادات Render =====
RENDER_PORT = int(os.getenv("PORT", "10000"))
WEB_PORT = get_env_or_default("WEB_PORT", RENDER_PORT, int)
if WEB_PORT == 8080 and RENDER_PORT != 8080:
    WEB_PORT = RENDER_PORT

WEB_HOST = get_env_or_default("WEB_HOST", "0.0.0.0", str)
WEB_PASSWORD = get_env_or_default("WEB_PASSWORD", "", str)
if not WEB_PASSWORD and os.getenv('ENVIRONMENT', 'development') == 'production':
    print("⚠️ تحذير أمني: WEB_PASSWORD غير معيّنة في بيئة الإنتاج! سيتم طلب كلمة مرور عشوائية.")
    WEB_PASSWORD = secrets.token_urlsafe(16)
    print(f"🔑 كلمة المرور المؤقتة: {WEB_PASSWORD}")
WEB_USERNAME = get_env_or_default("WEB_USERNAME", "admin", str)
WEB_SECRET_KEY = get_env_or_default("WEB_SECRET_KEY", secrets.token_urlsafe(32), str)
WEB_SESSION_TIMEOUT = get_env_or_default("WEB_SESSION_TIMEOUT", 3600, int)
WEB_RATE_LIMIT = get_env_or_default("WEB_RATE_LIMIT", 100, int)
WEB_RATE_WINDOW = get_env_or_default("WEB_RATE_WINDOW", 60, int)

BATTERY_SAVER_MODE = get_env_or_default("BATTERY_SAVER_MODE", False, bool)

DEFAULT_PUBLISH_INTERVAL_SECONDS = 720
CLEANUP_SLEEP = 3600

if BATTERY_SAVER_MODE:
    POLL_INTERVAL = 10.0
    SCHEDULED_POSTS_SLEEP = 120
    REMINDERS_SLEEP = 7200
    AUTO_BACKUP_SLEEP = 48 * 60 * 60
else:
    POLL_INTERVAL = 1.0
    SCHEDULED_POSTS_SLEEP = 10
    REMINDERS_SLEEP = 3600
    AUTO_BACKUP_SLEEP = 24 * 60 * 60

# ===================== التشفير المعتمد على كلمة المرور =====================
def derive_key_from_password(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key

def get_encryption_key() -> bytes:
    key_file = DATA_PATH / ".db_key"
    salt_file = DATA_PATH / ".db_salt"

    # محاولة تحميل المفتاح من ملف
    if key_file.exists() and salt_file.exists():
        try:
            with open(key_file, 'rb') as f:
                key = f.read()
            return key
        except:
            pass

    # محاولة استخدام كلمة المرور من متغير البيئة
    password = os.getenv('DB_ENCRYPTION_PASSWORD')
    if password and len(password) >= 8:
        salt = os.urandom(16)
        key = derive_key_from_password(password, salt)
        try:
            with open(key_file, 'wb') as f:
                f.write(key)
            with open(salt_file, 'wb') as f:
                f.write(salt)
        except:
            pass
        print("✅ تم إنشاء مفتاح التشفير من متغير البيئة")
        return key

    # في بيئة غير تفاعلية (مثل Render)، إنشاء مفتاح عشوائي
    if not sys.stdin.isatty():
        print("🔐 بيئة غير تفاعلية - إنشاء مفتاح عشوائي")
        key = Fernet.generate_key()
        try:
            with open(key_file, 'wb') as f:
                f.write(key)
        except:
            pass
        return key

    # بيئة تفاعلية - طلب كلمة مرور من المستخدم
    try:
        import getpass
        print("🔐 لإعداد تشفير قاعدة البيانات، أدخل كلمة مرور قوية:")
        password = getpass.getpass("كلمة المرور: ")
        confirm = getpass.getpass("تأكيد كلمة المرور: ")

        if password != confirm:
            print("❌ كلمات المرور غير متطابقة!")
            sys.exit(1)

        if len(password) < 8:
            print("❌ كلمة المرور يجب أن تكون 8 أحرف على الأقل!")
            sys.exit(1)

        salt = os.urandom(16)
        key = derive_key_from_password(password, salt)

        with open(key_file, 'wb') as f:
            f.write(key)
        with open(salt_file, 'wb') as f:
            f.write(salt)

        print("✅ تم إنشاء مفتاح التشفير وحفظه بشكل آمن")
        return key
    except:
        print("⚠️ فشل في الحصول على كلمة المرور - استخدام مفتاح عشوائي")
        key = Fernet.generate_key()
        try:
            with open(key_file, 'wb') as f:
                f.write(key)
        except:
            pass
        return key

ENCRYPTION_KEY = get_encryption_key()
cipher_suite = Fernet(ENCRYPTION_KEY)

# ===================== مفتاح منفصل للنسخ الاحتياطي =====================
def get_backup_encryption_key() -> bytes:
    backup_key_file = DATA_PATH / ".backup_key"
    if backup_key_file.exists():
        try:
            with open(backup_key_file, 'rb') as f:
                return f.read()
        except:
            pass

    new_key = Fernet.generate_key()
    try:
        with open(backup_key_file, 'wb') as f:
            f.write(new_key)
    except:
        pass
    print("✅ تم توليد مفتاح جديد لتشفير النسخ الاحتياطية")
    return new_key

BACKUP_ENCRYPTION_KEY = get_backup_encryption_key()
BACKUP_CIPHER = Fernet(BACKUP_ENCRYPTION_KEY)

# ===================== متغيرات تشغيل الخلفية =====================
_background_tasks_started = False

# ===================== تحسينات التخزين المؤقت =====================
try:
    from cachetools import TTLCache, LRUCache
    CACHETOOLS_AVAILABLE = True
    _admin_cache = TTLCache(maxsize=1000, ttl=300)
    _security_cache = TTLCache(maxsize=500, ttl=60)
    _translation_cache = LRUCache(maxsize=200)
    _auth_cache = TTLCache(maxsize=1000, ttl=300)
except ImportError:
    CACHETOOLS_AVAILABLE = False
    _admin_cache = {}
    _security_cache = {}
    _translation_cache = {}
    _auth_cache = {}
    _ADMIN_CACHE_TTL = 60
    _SECURITY_CACHE_TTL = 30
    _TRANSLATION_CACHE_SIZE = 500
    _AUTH_CACHE_TTL = 300

_security_cache_time = {}
_security_cache_ttl = 30

_translation_cache_lock = asyncio.Lock()
user_translation_settings_cache = {}
_user_translation_cache_lock = asyncio.Lock()

# ===================== تخزين مؤقت محسن للترجمة =====================
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

# ===================== دالة is_authorized_in_group (مع التخزين المؤقت) =====================
async def is_authorized_in_group(bot, chat_id: int, user_id: int) -> bool:
    """
    التحقق مما إذا كان المستخدم مشرفاً في المجموعة (حقيقي أو مالك مخفي أو مشرف مخفي).
    يتم تخزين النتيجة مؤقتاً لتقليل استعلامات قاعدة البيانات.
    """
    if user_id == PRIMARY_OWNER_ID:
        return True

    cache_key = f"auth_{chat_id}_{user_id}"
    if CACHETOOLS_AVAILABLE:
        if cache_key in _auth_cache:
            return _auth_cache[cache_key]
    else:
        if cache_key in _auth_cache:
            cached_time, value = _auth_cache[cache_key]
            if time_module.time() - cached_time < _AUTH_CACHE_TTL:
                return value

    # التحقق من الصلاحيات
    authorized = False

    # 1. مشرف حقيقي (من جدول group_admins)
    if await db_is_real_admin(chat_id, user_id):
        authorized = True

    # 2. مالك مخفي
    if not authorized and await db_is_hidden_owner(chat_id, user_id):
        authorized = True

    # 3. مشرف مخفي
    if not authorized and await db_is_hidden_admin(chat_id, user_id):
        authorized = True

    # تخزين النتيجة
    if CACHETOOLS_AVAILABLE:
        _auth_cache[cache_key] = authorized
    else:
        _auth_cache[cache_key] = (time_module.time(), authorized)

    return authorized

# ===================== دالة invalidate_auth_cache =====================
def invalidate_auth_cache(chat_id: int = None, user_id: int = None):
    """إبطال التخزين المؤقت للصلاحيات عند التغيير"""
    if chat_id is not None and user_id is not None:
        cache_key = f"auth_{chat_id}_{user_id}"
        if CACHETOOLS_AVAILABLE:
            _auth_cache.pop(cache_key, None)
        else:
            _auth_cache.pop(cache_key, None)
    elif chat_id is not None:
        keys_to_remove = [k for k in _auth_cache.keys() if k.startswith(f"auth_{chat_id}_")]
        for k in keys_to_remove:
            _auth_cache.pop(k, None)
    else:
        _auth_cache.clear()

# ===================== التحقق من التشغيل الواحد =====================
def check_single_instance():
    try:
        sock_path = TEMP_PATH / "bot.sock"
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(str(sock_path))
            return sock
        except socket.error:
            print("❌ البوت يعمل بالفعل!")
            sys.exit(1)
    except Exception as e:
        print(f"⚠️ لا يمكن التحقق من التشغيل الواحد: {e}")
        return None

lock_socket = check_single_instance()

# ===================== دوال التنظيف والتهرب =====================
def clean_text_for_telegram(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\u200b\u200c\u200d\u2060\uFEFF\u202a\u202b\u202c\u202d\u202e]', '', text)
    return text

def escape_markdown_v2(text: str) -> str:
    if not text:
        return ""
    special_chars = r'_*[]()~`>#+\-=|{}.!'
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def sanitize_text(text: str, max_length: int = 4096, allow_tags: list = None) -> str:
    if not text:
        return ""
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
    except:
        cleaned = text
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned

def encode_callback_data(data: str) -> str:
    return urllib.parse.quote(data, safe='')

def decode_callback_data(data: str) -> str:
    return urllib.parse.unquote(data)

ERROR_MESSAGES = {
    "Forbidden": "🔒 البوت ليس لديه صلاحية للقيام بهذا الإجراء",
    "BadRequest": "⚠️ طلب غير صحيح، تأكد من البيانات المدخلة",
    "TimedOut": "⏱️ انتهت المهلة، حاول مرة أخرى",
    "NetworkError": "🌐 مشكلة في الشبكة، تحقق من اتصالك",
    "InvalidQuery": "❌ بيانات غير صالحة، حاول مرة أخرى",
    "ChatNotFound": "❌ المجموعة غير موجودة أو البوت ليس فيها",
    "UserNotFound": "❌ المستخدم غير موجود",
    "MessageNotModified": "✅ تم التحديث",
}

def get_user_friendly_error(error: Exception) -> str:
    error_type = type(error).__name__
    return ERROR_MESSAGES.get(error_type, f"❌ حدث خطأ: {str(error)[:100]}")

# ===================== نظام سجلات متقدم =====================
class AdvancedLogger:
    def __init__(self):
        self.loggers = {}
        self._setup_loggers()

    def _setup_loggers(self):
        # Logger للأخطاء
        error_logger = logging.getLogger('error_logger')
        error_logger.setLevel(logging.ERROR)
        error_handler = logging.FileHandler(ERROR_LOG, encoding='utf-8')
        error_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        error_logger.addHandler(error_handler)
        self.loggers['error'] = error_logger

        # Logger للوصول
        access_logger = logging.getLogger('access_logger')
        access_logger.setLevel(logging.INFO)
        access_handler = logging.FileHandler(ACCESS_LOG, encoding='utf-8')
        access_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        access_logger.addHandler(access_handler)
        self.loggers['access'] = access_logger

        # Logger للأمان
        security_logger = logging.getLogger('security_logger')
        security_logger.setLevel(logging.WARNING)
        security_handler = logging.FileHandler(SECURITY_LOG, encoding='utf-8')
        security_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        security_logger.addHandler(security_handler)
        self.loggers['security'] = security_logger

    def log_error(self, message: str, error: Exception = None, context: dict = None):
        error_id = secrets.token_hex(4)
        log_msg = f"[{error_id}] {message}"
        if error:
            log_msg += f" - {error}"
        if context:
            log_msg += f" - السياق: {json.dumps(context, default=str)[:200]}"
        self.loggers['error'].error(log_msg)
        traceback.print_exc()
        return error_id

    def log_access(self, user_id: int, action: str, details: dict = None):
        log_msg = f"User: {user_id} - Action: {action}"
        if details:
            log_msg += f" - {json.dumps(details, default=str)[:100]}"
        self.loggers['access'].info(log_msg)

    def log_security(self, event: str, user_id: int, details: dict = None, severity: str = "INFO"):
        log_msg = f"[{severity}] {event} - User: {user_id}"
        if details:
            log_msg += f" - {json.dumps(details, default=str)[:200]}"
        self.loggers['security'].warning(log_msg)

advanced_logger = AdvancedLogger()

# ===================================================================
# ===================== إضافة دالة log_error =====================
# ===================================================================
def log_error(error: Exception, context: dict = None) -> str:
    """تسجيل الأخطاء وإرجاع معرف فريد"""
    return advanced_logger.log_error("حدث خطأ غير متوقع", error, context)

# ===================================================================

# ===================== نظام إدارة الأخطاء =====================
class ErrorHandler:
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.errors = defaultdict(int)
        self._lock = asyncio.Lock()

    async def handle_async(self, func: Callable, *args, **kwargs) -> Any:
        """معالجة دالة غير متزامنة مع إعادة المحاولة"""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return await func(*args, **kwargs)
            except (TimedOut, NetworkError) as e:
                last_error = e
                delay = self.base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                advanced_logger.log_error(f"محاولة {attempt+1} فشلت", e, {'args': str(args)[:100]})
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(delay)
                continue
            except Conflict as e:
                advanced_logger.log_error("تعارض في التحديثات", e)
                return None
            except Forbidden as e:
                advanced_logger.log_security("FORBIDDEN_ACTION", 0, {'error': str(e)}, "CRITICAL")
                raise
            except Exception as e:
                advanced_logger.log_error("خطأ غير متوقع", e, {'args': str(args)[:100]})
                raise
        if last_error:
            raise last_error
        return None

    def handle_sync(self, func: Callable, *args, **kwargs) -> Any:
        """معالجة دالة متزامنة مع إعادة المحاولة"""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                delay = self.base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                advanced_logger.log_error(f"محاولة {attempt+1} فشلت (متزامنة)", e)
                if attempt < self.max_retries - 1:
                    time_module.sleep(delay)
                continue
        if last_error:
            raise last_error
        return None

error_handler = ErrorHandler()

# ===================== نظام إدارة الذاكرة =====================
def memory_optimizer():
    """تحسين استخدام الذاكرة"""
    try:
        # تنظيف الكاش
        if CACHETOOLS_AVAILABLE:
            _admin_cache.clear()
            _security_cache.clear()
            _auth_cache.clear()
        else:
            _admin_cache.clear()
            _security_cache.clear()
            _auth_cache.clear()
            _security_cache_time.clear()

        # تنظيف كاش الترجمة
        _translation_cache.clear()

        # تنظيف كاش NSFW
        NSFW_CACHE.clear()

        # جمع القمامة
        gc.collect()

        return True
    except Exception as e:
        advanced_logger.log_error("فشل تحسين الذاكرة", e)
        return False

async def memory_optimizer_loop():
    """حلقة تحسين الذاكرة التلقائية"""
    while True:
        await asyncio.sleep(300)  # كل 5 دقائق
        try:
            memory_optimizer()
            advanced_logger.log_access(0, "MEMORY_OPTIMIZED", {"timestamp": utc_now_iso()})
        except Exception as e:
            advanced_logger.log_error("فشل حلقة تحسين الذاكرة", e)

# ===================== نظام الإشعارات المتقدم =====================
class NotificationSystem:
    def __init__(self):
        self.pending_notifications = []
        self._lock = asyncio.Lock()
        self._scheduled_tasks = []

    async def send_notification(self, bot, user_id: int, text: str, parse_mode: str = "MarkdownV2", reply_markup=None):
        """إرسال إشعار لمستخدم"""
        try:
            await safe_send_markdown(bot, user_id, text, reply_markup)
            advanced_logger.log_access(user_id, "NOTIFICATION_SENT", {"text": text[:50]})
            return True
        except Exception as e:
            advanced_logger.log_error("فشل إرسال الإشعار", e, {"user_id": user_id})
            return False

    async def send_bulk_notification(self, bot, user_ids: List[int], text: str, parse_mode: str = "MarkdownV2", delay: float = 0.5):
        """إرسال إشعار لمجموعة من المستخدمين"""
        results = []
        semaphore = asyncio.Semaphore(10)

        async def send_one(user_id):
            async with semaphore:
                try:
                    await safe_send_markdown(bot, user_id, text)
                    return (user_id, True)
                except:
                    await asyncio.sleep(delay)
                    return (user_id, False)

        tasks = [send_one(uid) for uid in user_ids]
        results = await asyncio.gather(*tasks)

        success = sum(1 for _, ok in results if ok)
        failed = len(results) - success

        advanced_logger.log_access(0, "BULK_NOTIFICATION", {
            "total": len(user_ids),
            "success": success,
            "failed": failed
        })

        return success, failed

    async def schedule_notification(self, bot, user_id: int, text: str, delay_seconds: int):
        """جدولة إشعار لاحقاً"""
        async def delayed():
            await asyncio.sleep(delay_seconds)
            await self.send_notification(bot, user_id, text)

        task = asyncio.create_task(delayed())
        self._scheduled_tasks.append(task)
        task.add_done_callback(lambda t: self._scheduled_tasks.remove(t) if t in self._scheduled_tasks else None)
        return task

notification_system = NotificationSystem()

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
    except BadRequest as e:
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
    """تعديل رسالة بأمان مع دعم MarkdownV2 وتجنب خطأ 'message is not modified'"""
    if not query or not query.message:
        return None
    
    # تحقق إذا كانت الرسالة نفسها
    current_text = query.message.text or ""
    current_reply_markup = query.message.reply_markup
    
    if current_text == text:
        if reply_markup is None and current_reply_markup is None:
            try:
                await query.answer("✅ تم التحديث")
            except:
                pass
            return None
        elif reply_markup is not None and current_reply_markup is not None:
            if str(reply_markup) == str(current_reply_markup):
                try:
                    await query.answer("✅ تم التحديث")
                except:
                    pass
                return None
    
    if not text:
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
    except BadRequest as e:
        error_msg = str(e).lower()
        if "can't parse entities" in error_msg:
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
        elif "message is not modified" in error_msg:
            try:
                await query.answer("✅ تم التحديث")
            except:
                pass
            return None
        raise

async def safe_send_error(bot, chat_id: int, text: str):
    try:
        return await safe_send_markdown(bot, chat_id, text)
    except Exception as e:
        logger.warning(f"فشل إرسال تقرير الخطأ: {e}")
        plain_text = re.sub(r'[*_`\[\]()~>#+\-=|{}.!\\]', '', text)
        plain_text = plain_text.replace("\\", "")
        try:
            return await bot.send_message(chat_id=chat_id, text=plain_text[:4000])
        except Exception as e2:
            return await bot.send_message(chat_id=chat_id, text=text[:4000], parse_mode=None)

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

# ===================== نظام التسجيل المحسن =====================
class CustomFormatter(logging.Formatter):
    def format(self, record):
        msg = super().format(record)
        if TOKEN and TOKEN in msg:
            msg = msg.replace(TOKEN, "[TOKEN_HIDDEN]")
        if ENCRYPTION_KEY and isinstance(ENCRYPTION_KEY, bytes):
            try:
                key_str = ENCRYPTION_KEY.decode()
                if key_str in msg:
                    msg = msg.replace(key_str, "[ENCRYPTION_KEY_HIDDEN]")
            except:
                pass
        if BACKUP_ENCRYPTION_KEY and isinstance(BACKUP_ENCRYPTION_KEY, bytes):
            try:
                key_str = BACKUP_ENCRYPTION_KEY.decode()
                if key_str in msg:
                    msg = msg.replace(key_str, "[BACKUP_KEY_HIDDEN]")
            except:
                pass
        return msg

from logging.handlers import RotatingFileHandler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        RotatingFileHandler(
            LOG_PATH,
            maxBytes=10*1024*1024,
            backupCount=5,
            encoding='utf-8'
        ),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class LogLevel:
    SECURITY = 25
    PERFORMANCE = 15

logging.addLevelName(LogLevel.SECURITY, "SECURITY")
logging.addLevelName(LogLevel.PERFORMANCE, "PERFORMANCE")

def log_performance(operation: str, duration: float):
    logger.log(LogLevel.PERFORMANCE, f"{operation} took {duration:.3f}s")

for handler in logger.handlers:
    handler.setFormatter(CustomFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")))

# ===================== نظام الأمان والتدقيق =====================
class SecurityAudit:
    async def log(self, event_type: str, user_id: int, details: dict, severity: str = "INFO"):
        log_entry = {
            "event": event_type,
            "user_id": user_id,
            "details": details,
            "severity": severity,
            "timestamp": mecca_now_iso()
        }
        logger.warning(f"[SECURITY] {event_type} | User: {user_id} | {details} | Severity: {severity}")
        advanced_logger.log_security(event_type, user_id, details, severity)
        try:
            with open(SECURITY_LOG, "a", encoding='utf-8') as f:
                f.write(json.dumps(log_entry) + "\n")
        except:
            pass

        try:
            log_channel = await db_get_log_channel_id()
            if log_channel:
                try:
                    from telegram import Bot
                    bot = Bot(token=TOKEN)
                    await bot.send_message(
                        chat_id=log_channel,
                        text=f"🔐 **تقرير أمني**\n\n📌 الحدث: {event_type}\n👤 المستخدم: `{user_id}`\n📊 التفاصيل: {json.dumps(details, default=str)[:200]}\n⚠️ الخطورة: {severity}\n🕐 الوقت: {mecca_now().strftime('%Y-%m-%d %H:%M:%S')}",
                        parse_mode="MarkdownV2"
                    )
                except Exception as e:
                    logger.warning(f"فشل إرسال التقرير إلى القناة: {e}")
        except:
            pass

        return True

security_audit = SecurityAudit()

# ===================== نظام كشف النشاط المشبوه =====================
class AnomalyDetector:
    def __init__(self):
        self.user_activity = defaultdict(list)
        self.lock = asyncio.Lock()

    async def detect_anomaly(self, user_id: int, action: str) -> bool:
        async with self.lock:
            now = time_module.time()
            self.user_activity[user_id].append((now, action))
            self.user_activity[user_id] = [
                (t, a) for t, a in self.user_activity[user_id]
                if now - t < 60
            ]
            if len(self.user_activity[user_id]) > 10:
                await security_audit.log(
                    "SUSPICIOUS_ACTIVITY",
                    user_id,
                    {"actions": self.user_activity[user_id], "count": len(self.user_activity[user_id])},
                    "CRITICAL"
                )
                return True
            return False

anomaly_detector = AnomalyDetector()

# ===================== Pool اتصالات قاعدة البيانات =====================
class DatabasePool:
    def __init__(self, max_connections: int = 10):
        self._pool = None
        self._max_connections = max_connections
        self._lock = asyncio.Lock()
        self._connections = []

    async def initialize(self):
        async with self._lock:
            if self._pool is None:
                self._pool = await aiosqlite.connect(str(DB_PATH), timeout=DB_TIMEOUT)
                await self._pool.execute("PRAGMA journal_mode=WAL")
                await self._pool.execute("PRAGMA synchronous=NORMAL")
                await self._pool.execute("PRAGMA foreign_keys=ON")
                await self._pool.execute("PRAGMA cache_size=-64000")
                await self._pool.execute("PRAGMA max_page_count=1000000")
                await self._pool.execute("PRAGMA secure_delete=ON")
                self._pool.row_factory = aiosqlite.Row

    async def get_connection(self):
        if self._pool is None:
            await self.initialize()
        return self._pool

    async def execute(self, query: str, params: tuple = None):
        conn = await self.get_connection()
        async with conn.execute(query, params or ()) as cursor:
            return await cursor.fetchall()

    async def execute_many(self, queries: List[Tuple[str, tuple]]):
        conn = await self.get_connection()
        async with conn:
            for query, params in queries:
                await conn.execute(query, params)
            await conn.commit()

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None

db_pool = DatabasePool(max_connections=MAX_CONNECTIONS)

async def execute_db(func: Callable):
    conn = await db_pool.get_connection()
    try:
        return await func(conn)
    except Exception as e:
        logger.error(f"خطأ في قاعدة البيانات: {e}")
        raise
    finally:
        pass

async def execute_transaction(queries: List[Tuple[str, tuple]]) -> Any:
    conn = await db_pool.get_connection()
    try:
        async with conn:
            results = []
            for query, params in queries:
                cur = await conn.execute(query, params)
                if query.strip().upper().startswith('SELECT'):
                    results.append(await cur.fetchall())
            await conn.commit()
            return results if len(results) > 1 else (results[0] if results else None)
    except Exception as e:
        await conn.rollback()
        raise

# ===================== نظام التخزين المؤقت باستخدام Redis =====================
try:
    import aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    print("⚠️ مكتبة aioredis غير مثبتة، سيتم استخدام التخزين المؤقت في الذاكرة")

class CacheManager:
    def __init__(self):
        self.redis = None
        self.use_redis = REDIS_AVAILABLE and os.getenv("REDIS_URL")
        self.local_cache = {}

    async def init(self):
        if self.use_redis:
            try:
                self.redis = await aioredis.from_url(os.getenv("REDIS_URL"))
                await self.redis.ping()
                logger.info("✅ تم الاتصال بـ Redis")
            except Exception as e:
                logger.warning(f"⚠️ فشل الاتصال بـ Redis: {e}")
                self.use_redis = False

    async def get(self, key: str):
        if self.use_redis:
            try:
                value = await self.redis.get(key)
                if value:
                    return json.loads(value)
            except:
                pass
        return self.local_cache.get(key)

    async def set(self, key: str, value: Any, ttl: int = 300):
        if self.use_redis:
            try:
                await self.redis.setex(key, ttl, json.dumps(value))
                return
            except:
                pass
        self.local_cache[key] = value

    async def delete(self, key: str):
        if self.use_redis:
            try:
                await self.redis.delete(key)
            except:
                pass
        self.local_cache.pop(key, None)

cache_manager = CacheManager()

# ===================== دوال التشفير المحسنة =====================
def init_db_encryption():
    pass

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

def encrypt_db_backup() -> Path:
    if not DB_ENCRYPTION:
        return DB_PATH
    cipher = Fernet(ENCRYPTION_KEY)
    encrypted_path = DB_PATH.with_suffix('.enc')
    encrypt_file_stream(DB_PATH, encrypted_path, cipher)
    return encrypted_path

def decrypt_db_backup(encrypted_path: Path) -> bytes:
    if not DB_ENCRYPTION:
        with open(encrypted_path, 'rb') as f:
            return f.read()
    cipher = Fernet(ENCRYPTION_KEY)
    temp_decrypted = encrypted_path.with_suffix('.db.tmp')
    decrypt_file_stream(encrypted_path, temp_decrypted, cipher)
    with open(temp_decrypted, 'rb') as f:
        data = f.read()
    temp_decrypted.unlink()
    return data

def compress_backup(data: bytes) -> bytes:
    if ZSTD_AVAILABLE:
        try:
            return ZSTD_COMPRESSOR.compress(data)
        except:
            pass
    return gzip.compress(data)

def decompress_backup(data: bytes) -> bytes:
    if ZSTD_AVAILABLE:
        try:
            return ZSTD_DECOMPRESSOR.decompress(data)
        except:
            pass
    return gzip.decompress(data)

# ===================== نظام Backoff ذكي مع Jitter =====================
async def retry_with_jitter(func: Callable, max_retries: int = 5, base_delay: float = 1) -> Any:
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            jitter = random.uniform(0, 0.5)
            delay = (base_delay * (2 ** attempt)) + jitter
            logger.warning(f"⚠️ إعادة محاولة {attempt+1}/{max_retries} بعد {delay:.2f}s: {e}")
            await asyncio.sleep(delay)

def retry(max_retries=3, delay=1, backoff=2, exceptions=(Exception,)):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            _delay = delay
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries - 1:
                        raise
                    jitter = random.uniform(0, 0.5)
                    await asyncio.sleep(_delay + jitter)
                    _delay *= backoff
            return None
        return wrapper
    return decorator

# ===================== نظام Rate Limiting =====================
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

# ===================== تحسينات نظام الترجمة =====================
class AsyncTranslator:
    def __init__(self):
        self.session = None
        self.pending = defaultdict(list)

    async def get_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session

    async def translate(self, text: str, target: str) -> str:
        if not text or len(text.strip()) == 0:
            return text
        if target not in SUPPORTED_LANGUAGES and target != 'auto':
            return text
        cache_key = hashlib.md5(f"{text}_{target}".encode()).hexdigest()
        cached = await _translation_cache.get(cache_key)
        if cached:
            return cached
        if text in self.pending:
            future = asyncio.Future()
            self.pending[text].append(future)
            return await future
        self.pending[text] = []
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
                for future in self.pending[text]:
                    if not future.done():
                        future.set_result(translated)
                return translated
        except Exception as e:
            logger.error(f"خطأ في الترجمة: {e}")
            for future in self.pending[text]:
                if not future.done():
                    future.set_result(text)
            return text
        finally:
            if text in self.pending:
                del self.pending[text]

smart_translator = AsyncTranslator()

async def translate_text(text: str, target_lang: str, source_lang: str = 'auto') -> str:
    return await smart_translator.translate(text, target_lang)

async def get_user_translation_language(user_id: int) -> str:
    async with _user_translation_cache_lock:
        if user_id in user_translation_settings_cache:
            return user_translation_settings_cache[user_id]
    async def _get(conn):
        cur = await conn.execute("SELECT lang FROM user_translation WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 'off'
    lang = await execute_db(_get)
    async with _user_translation_cache_lock:
        user_translation_settings_cache[user_id] = lang
    return lang

async def set_user_translation_language(user_id: int, lang: str):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO user_translation (user_id, lang) VALUES (?, ?)", (user_id, lang))
        await conn.commit()
    await execute_db(_set)
    async with _user_translation_cache_lock:
        user_translation_settings_cache[user_id] = lang

# ===================== نظام اللغة =====================
_user_language_lock = asyncio.Lock()

async def set_user_language_async(user_id: int, lang: str):
    async with _user_language_lock:
        user_language[user_id] = lang

def get_text_local(user_id: int, key: str) -> str:
    """دالة محلية للحصول على النص (تستخدم داخل الكود)"""
    return get_text(user_id, key)

async def get_user_language(user_id: int) -> str:
    return user_language.get(user_id, 'ar')

# ===================== دوال القوائم والأزرار (الكيبورد) =====================
class CallbackData:
    MAIN_MENU = "main_menu"
    CHANNELS_MY = "channels:my_channels"
    CHANNELS_ADD = "channels:add"
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
    BACK = "back"
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
    GROUP_MUTE_PREFIX = "group_mute:"
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
    # الأزرار الجديدة
    SECURITY_DELETE_VIDEOS_PREFIX = "security:delete_videos:"
    SECURITY_DELETE_SERVICE_PREFIX = "security:delete_service:"
    SECURITY_DELETE_DOCUMENTS_PREFIX = "security:delete_documents:"
    SECURITY_DELETE_STICKERS_PREFIX = "security:delete_stickers:"
# ===================== نظام إدارة الحالات المتقدم =====================
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

class StateDispatcher:
    def __init__(self):
        self.handlers = {}

    def register(self, state: UserState, handler: Callable):
        self.handlers[state] = handler

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        user_id = update.effective_user.id
        state = context.user_data.get('state')
        if state is None or state == UserState.NONE:
            return False
        handler = self.handlers.get(state)
        if handler:
            return await handler(update, context, state)
        return False

state_dispatcher = StateDispatcher()

# ===================== دوال قاعدة البيانات الأساسية =====================
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
        if row and row[0]:
            try:
                current_end = datetime.fromisoformat(row[0])
                if current_end > utc_now():
                    new_end = current_end + timedelta(days=days)
                else:
                    new_end = utc_now() + timedelta(days=days)
            except:
                new_end = utc_now() + timedelta(days=days)
        else:
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

# ===================== دوال auto_recycle =====================
async def db_get_auto_recycle(user_id: int) -> bool:
    async def _get(conn):
        cur = await conn.execute("SELECT auto_recycle FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_get)

async def db_set_auto_recycle(user_id: int, enabled: bool):
    async def _set(conn):
        await conn.execute("UPDATE users SET auto_recycle=? WHERE user_id=?", (1 if enabled else 0, user_id))
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
            logger.error(f"خطأ في جلب قنوات المستخدم {user_id}: {e}")
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

async def db_get_all_user_channels_no_limit():
    async def _get(conn):
        cur = await conn.execute("SELECT uc.user_id, uc.id, uc.channel_id, uc.channel_name, uc.banned FROM user_channels uc ORDER BY uc.id")
        return await cur.fetchall()
    return await execute_db(_get)

async def db_all_users_channels(only_banned: bool = False, limit: int = 500):
    async def _get(conn):
        if only_banned:
            cur = await conn.execute("SELECT user_id, id, channel_id, channel_name, banned FROM user_channels WHERE banned=1 LIMIT ?", (limit,))
        else:
            cur = await conn.execute("SELECT user_id, id, channel_id, channel_name, banned FROM user_channels LIMIT ?", (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_register_channel(channel_id: int, channel_name: str, added_by: int):
    async def _register(conn):
        cur = await conn.execute("SELECT channel_id FROM bot_channels WHERE channel_id=?", (channel_id,))
        if await cur.fetchone():
            await conn.execute("UPDATE bot_channels SET channel_name=?, added_by=? WHERE channel_id=?", (channel_name, added_by, channel_id))
            await conn.commit()
            return False
        await conn.execute("INSERT INTO bot_channels (channel_id, channel_name, added_by, added_at) VALUES (?, ?, ?, ?)",
                          (channel_id, channel_name, added_by, utc_now_iso()))
        await conn.commit()
        return True
    return await execute_db(_register)

async def db_get_all_bot_channels(only_banned: bool = False):
    async def _get(conn):
        if only_banned:
            cur = await conn.execute("SELECT channel_id, channel_name, added_by, added_at, banned FROM bot_channels WHERE banned=1 ORDER BY added_at DESC")
        else:
            cur = await conn.execute("SELECT channel_id, channel_name, added_by, added_at, banned FROM bot_channels ORDER BY added_at DESC")
        return await cur.fetchall()
    return await execute_db(_get)

# ===================== دوال المنشورات =====================
async def db_save_posts(channel_db_id: int, posts: list) -> int:
    async def _save(conn):
        values = []
        for text_content, media_type, media_file_id in posts:
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

async def db_update_post_views(post_id: int, views_count: int = None):
    async def _update_views(conn):
        if views_count is not None:
            await conn.execute(
                "UPDATE posts SET views_count = ?, last_view_time = ? WHERE id = ?",
                (views_count, utc_now_iso(), post_id)
            )
        else:
            await conn.execute(
                "UPDATE posts SET views_count = views_count + 1, last_view_time = ? WHERE id = ?",
                (utc_now_iso(), post_id)
            )
        await conn.commit()
    await execute_db(_update_views)

async def db_stats():
    async def _stats(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM users")
        total = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT COUNT(*) FROM users WHERE banned=1")
        banned = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE published=0")
        posts = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT COUNT(*) FROM bot_groups")
        groups = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT COUNT(*) FROM user_channels")
        channels = (await cur.fetchone())[0]
        return total, banned, posts, groups, channels
    return await execute_db(_stats)

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
        await conn.execute("INSERT OR IGNORE INTO group_admins (chat_id, user_id) VALUES (?, ?)", (chat_id, added_by))
        await conn.commit()
        return True
    return await execute_db(_register)

async def db_get_user_groups(user_id: int):
    async def _get(conn):
        try:
            cur = await conn.execute("""
                SELECT chat_id, chat_name, username, banned
                FROM bot_groups
                ORDER BY chat_name
            """)
            all_groups = await cur.fetchall()

            cur = await conn.execute("""
                SELECT chat_id FROM hidden_owner_groups WHERE owner_id=?
            """, (user_id,))
            hidden_owner_rows = await cur.fetchall()
            hidden_owner_groups = {row[0] for row in hidden_owner_rows}

            cur = await conn.execute("""
                SELECT chat_id FROM hidden_admins WHERE admin_id=?
            """, (user_id,))
            hidden_admin_rows = await cur.fetchall()
            hidden_admin_groups = {row[0] for row in hidden_admin_rows}

            cur = await conn.execute("""
                SELECT chat_id FROM bot_groups WHERE added_by=?
                UNION
                SELECT chat_id FROM user_groups_link WHERE user_id=?
            """, (user_id, user_id))
            linked_rows = await cur.fetchall()
            linked_groups = {row[0] for row in linked_rows}

            cur = await conn.execute("""
                SELECT chat_id FROM group_admins WHERE user_id=?
            """, (user_id,))
            admin_rows = await cur.fetchall()
            admin_groups = {row[0] for row in admin_rows}

            visible_groups = []
            for group in all_groups:
                chat_id = group[0]
                if chat_id in hidden_owner_groups:
                    visible_groups.append(group)
                elif chat_id in hidden_admin_groups:
                    continue
                elif chat_id in admin_groups:
                    visible_groups.append(group)
                elif chat_id in linked_groups:
                    visible_groups.append(group)
                else:
                    continue

            return visible_groups
        except Exception as e:
            logger.error(f"خطأ في جلب مجموعات المستخدم {user_id}: {e}")
            return []
    return await execute_db(_get)

async def db_get_user_groups_count(user_id: int) -> int:
    async def _get(conn):
        try:
            groups = await db_get_user_groups(user_id)
            return len(groups)
        except Exception as e:
            logger.error(f"خطأ في حساب عدد مجموعات المستخدم: {e}")
            return 0
    return await execute_db(_get)

async def db_get_all_groups(only_banned: bool = False):
    async def _get(conn):
        if only_banned:
            cur = await conn.execute("SELECT chat_id, chat_name, username, added_by, added_at, banned FROM bot_groups WHERE banned=1 ORDER BY added_at DESC")
        else:
            cur = await conn.execute("SELECT chat_id, chat_name, username, added_by, added_at, banned FROM bot_groups ORDER BY added_at DESC")
        return await cur.fetchall()
    return await execute_db(_get)

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
    default_settings = {
        'links': False, 'mentions': False, 'warn': True, 'slow_mode': False,
        'slow_mode_seconds': 5, 'welcome_enabled': False,
        'welcome_text': "مرحباً {user} في {chat} 🤍",
        'goodbye_enabled': False, 'goodbye_text': "وداعاً {user} 👋",
        'delete_banned_words': False, 'auto_penalty': 'none', 'auto_mute_duration': 60,
        'delete_videos': False,
        'delete_service': False,
        'delete_documents': False,
        'delete_stickers': False
    }

    if CACHETOOLS_AVAILABLE and chat_id in _security_cache:
        return _security_cache[chat_id]

    try:
        async def _get(conn):
            cur = await conn.execute(
                """SELECT delete_links, delete_mentions, warn_message, slow_mode,
                          slow_mode_seconds, welcome_enabled, welcome_text,
                          goodbye_enabled, goodbye_text, delete_banned_words,
                          auto_penalty, auto_mute_duration,
                          delete_videos, delete_service, delete_documents, delete_stickers
                   FROM group_security WHERE chat_id=?""",
                (chat_id,)
            )
            row = await cur.fetchone()
            if row:
                settings = {
                    'links': row[0] == 1,
                    'mentions': row[1] == 1,
                    'warn': row[2] == 1,
                    'slow_mode': row[3] == 1,
                    'slow_mode_seconds': row[4] if row[4] is not None else 5,
                    'welcome_enabled': row[5] == 1,
                    'welcome_text': row[6] if row[6] else default_settings['welcome_text'],
                    'goodbye_enabled': row[7] == 1,
                    'goodbye_text': row[8] if row[8] else default_settings['goodbye_text'],
                    'delete_banned_words': row[9] == 1,
                    'auto_penalty': row[10] if row[10] else 'none',
                    'auto_mute_duration': row[11] if row[11] is not None else 60,
                    'delete_videos': row[12] == 1 if len(row) > 12 else False,
                    'delete_service': row[13] == 1 if len(row) > 13 else False,
                    'delete_documents': row[14] == 1 if len(row) > 14 else False,
                    'delete_stickers': row[15] == 1 if len(row) > 15 else False
                }
                if CACHETOOLS_AVAILABLE:
                    _security_cache[chat_id] = settings
                return settings

            await conn.execute(
                """INSERT INTO group_security
                   (chat_id, delete_links, delete_mentions, warn_message, slow_mode,
                    slow_mode_seconds, welcome_enabled, welcome_text, goodbye_enabled,
                    goodbye_text, delete_banned_words, auto_penalty, auto_mute_duration,
                    delete_videos, delete_service, delete_documents, delete_stickers)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (chat_id, 0, 0, 1, 0, 5, 0, default_settings['welcome_text'],
                 0, default_settings['goodbye_text'], 0, 'none', 60,
                 0, 0, 0, 0)
            )
            await conn.commit()
            if CACHETOOLS_AVAILABLE:
                _security_cache[chat_id] = default_settings
            return default_settings
        return await execute_db(_get)
    except Exception as e:
        advanced_logger.log_error("خطأ في db_get_security_settings", e, {"chat_id": chat_id})
        return default_settings

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
                elif key == 'delete_videos':
                    updates.append("delete_videos=?")
                    values.append(1 if value else 0)
                elif key == 'delete_service':
                    updates.append("delete_service=?")
                    values.append(1 if value else 0)
                elif key == 'delete_documents':
                    updates.append("delete_documents=?")
                    values.append(1 if value else 0)
                elif key == 'delete_stickers':
                    updates.append("delete_stickers=?")
                    values.append(1 if value else 0)
            if updates:
                query = f"UPDATE group_security SET {', '.join(updates)} WHERE chat_id=?"
                values.append(chat_id)
                await conn.execute(query, values)
        else:
            await conn.execute(
                """INSERT INTO group_security (chat_id, delete_links, delete_mentions, warn_message, slow_mode, slow_mode_seconds, welcome_enabled, welcome_text, goodbye_enabled, goodbye_text, delete_banned_words, auto_penalty, auto_mute_duration, delete_videos, delete_service, delete_documents, delete_stickers)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (chat_id,
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
                  kwargs.get('auto_mute_duration', 60),
                  1 if kwargs.get('delete_videos', False) else 0,
                  1 if kwargs.get('delete_service', False) else 0,
                  1 if kwargs.get('delete_documents', False) else 0,
                  1 if kwargs.get('delete_stickers', False) else 0)
            )
        await conn.commit()
        if CACHETOOLS_AVAILABLE and chat_id in _security_cache:
            del _security_cache[chat_id]
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
    async def _get(conn):
        cur = await conn.execute("SELECT word, added_by, added_at FROM banned_words WHERE chat_id=? OR chat_id=-1 ORDER BY word", (chat_id,))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_contains_banned_word(text: str, chat_id: int) -> str:
    words = await db_get_banned_words(chat_id)
    text_lower = text.lower()
    for word, _, _ in words:
        if word in text_lower:
            return word
    for pattern in BANNED_PATTERNS:
        if pattern.search(text_lower):
            return pattern.pattern
    return None

async def add_banned_pattern(pattern: str) -> bool:
    try:
        compiled = re.compile(pattern.lower())
        BANNED_PATTERNS.append(compiled)
        return True
    except:
        return False

async def check_banned_patterns(text: str) -> bool:
    text_lower = text.lower()
    for pattern in BANNED_PATTERNS:
        if pattern.search(text_lower):
            return True
    return False

# ===================== دوال المالك والمشرفين المخفيين =====================
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
            logger.error(f"خطأ في إضافة مشرف مخفي: {e}")
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
        return [{'admin_id': row[0], 'added_by': row[1], 'added_at': row[2]} for row in rows]
    return await execute_db(_get)

async def db_get_all_hidden_admins(user_id: int) -> List[Dict]:
    async def _get(conn):
        cur = await conn.execute("""
            SELECT chat_id, added_at
            FROM hidden_admins
            WHERE admin_id=?
        """, (user_id,))
        rows = await cur.fetchall()
        return [{'chat_id': row[0], 'added_at': row[1]} for row in rows]
    return await execute_db(_get)

async def db_should_hide_group_from_user(chat_id: int, user_id: int) -> bool:
    async def _check(conn):
        if await db_is_hidden_owner(chat_id, user_id):
            return False
        if await db_is_hidden_admin(chat_id, user_id):
            return True
        return False
    return await execute_db(_check)

# ===================== دوال المشرفين الحقيقيين =====================
async def db_sync_group_admins(chat_id: int, bot, owner_id: int = None) -> int:
    try:
        admins = await bot.get_chat_administrators(chat_id)
        admin_ids = [admin.user.id for admin in admins]
        if owner_id and owner_id not in admin_ids:
            admin_ids.append(owner_id)

        async def _update(conn):
            await conn.execute("DELETE FROM group_admins WHERE chat_id=?", (chat_id,))
            if admin_ids:
                values = [(chat_id, uid) for uid in admin_ids]
                await conn.executemany("INSERT INTO group_admins (chat_id, user_id) VALUES (?, ?)", values)
                await conn.commit()
            return len(admin_ids)
        return await execute_db(_update)
    except Exception as e:
        logger.error(f"خطأ في مزامنة مشرفي المجموعة {chat_id}: {e}")
        return 0

async def db_is_real_admin(chat_id: int, user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT 1 FROM group_admins WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        return await cur.fetchone() is not None
    return await execute_db(_check)

# ===================== دوال الجدولة =====================
class ScheduleType(Enum):
    INTERVAL = "interval"
    CRON = "cron"
    RECURRING = "recurring"

async def db_save_schedule(channel_db_id: int, schedule_type: str, interval_minutes: int = None, interval_hours: int = None, interval_days: int = None, days_of_week: str = None, specific_dates: str = None, publish_time: str = None, cron_expression: str = None):
    async def _save(conn):
        await conn.execute("""
            INSERT OR REPLACE INTO schedule (channel_db_id, schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time, cron_expression, next_publish_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """, (channel_db_id, schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time or "00:00", cron_expression))
        await conn.commit()
    return await execute_db(_save)

async def db_get_schedule(channel_db_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time, cron_expression, next_publish_date FROM schedule WHERE channel_db_id=?", (channel_db_id,))
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
        return {'type': 'interval_minutes', 'interval_minutes': 12, 'interval_hours': 0, 'interval_days': 0, 'days_of_week': '[]', 'specific_dates': '[]', 'publish_time': '00:00', 'cron_expression': None, 'next_publish_date': None}
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

async def schedule_cron(channel_db_id: int, cron_expression: str):
    async def _save(conn):
        await conn.execute("""
            UPDATE schedule SET schedule_type='cron', cron_expression=?, next_publish_date=NULL
            WHERE channel_db_id=?
        """, (cron_expression, channel_db_id))
        await conn.commit()
    return await execute_db(_save)

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
            days_of_week = parse_days_of_week_safe(schedule.get('days_of_week', '[]'))
            if days_of_week:
                target_date = last_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
                found = False
                for i in range(1, 8):
                    check_date = target_date + timedelta(days=i)
                    if check_date.weekday() in days_of_week:
                        next_date = check_date
                        found = True
                        break
                if not found:
                    next_date = target_date + timedelta(days=7)
                    while next_date.weekday() not in days_of_week:
                        next_date += timedelta(days=1)
            else:
                next_date = last_time + timedelta(days=1)
        elif schedule_type == 'dates':
            specific_dates = parse_dates_safe(schedule.get('specific_dates', '[]'))
            if specific_dates:
                target_date = last_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
                for date_str in sorted(specific_dates):
                    try:
                        date_obj = datetime.strptime(date_str, '%Y-%m-%d').replace(hour=hour, minute=minute, second=0, microsecond=0)
                        if date_obj > last_time:
                            next_date = date_obj
                            break
                    except:
                        continue
                if not next_date:
                    try:
                        next_date = datetime.strptime(specific_dates[0], '%Y-%m-%d').replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=365)
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
        cur = await conn.execute("SELECT subscription_reminder, daily_stats_reminder, weekly_report, reminder_days_before, last_reminder_sent, notification_lang FROM user_reminder_settings WHERE user_id=?", (user_id,))
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
            await conn.execute("INSERT INTO user_reminder_settings (user_id, subscription_reminder, daily_stats_reminder, weekly_report, reminder_days_before, last_reminder_sent, notification_lang) VALUES (?, 1, 0, 1, 3, 0, 'ar')", (user_id,))
            await conn.commit()
            return {'subscription_reminder': True, 'daily_stats_reminder': False, 'weekly_report': True, 'reminder_days_before': 3, 'last_reminder_sent': 0, 'notification_lang': 'ar'}
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
                        users.append({'user_id': user_id, 'days_left': days_left, 'notification_lang': settings['notification_lang']})
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
LEVEL_REQUIREMENTS = {1: 0, 2: 100, 3: 250, 4: 500, 5: 1000, 6: 2000, 7: 3500, 8: 5000, 9: 7500, 10: 10000}

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

user_points_last_hour = defaultdict(lambda: (0, 0.0))

async def add_points(user_id: int, update: Update = None, context: ContextTypes.DEFAULT_TYPE = None):
    now = utc_now()
    count, last_timestamp = user_points_last_hour.get(user_id, (0, 0.0))
    if last_timestamp > 0:
        last_time = datetime.fromtimestamp(last_timestamp)
        last_time = to_naive(last_time)
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
    if new_levels and update and update.effective_user and context:
        try:
            if len(new_levels) == 1:
                msg = f"🎉 **تهانينا!**\nلقد وصلت إلى المستوى {new_levels[0]}! 🎉"
            else:
                msg = f"🎉 **تهانينا!**\nلقد تقدمت {len(new_levels)} مستويات إلى المستوى {new_levels[-1]}! 🎉"
            await safe_send_markdown(context.bot, user_id, msg)
        except:
            pass
    await db_update_user_level(user_id, points, level)

async def get_rank(user_id: int) -> dict:
    return await db_get_user_level(user_id)

async def get_top_users(limit: int = 10):
    async def _get(conn):
        cur = await conn.execute("SELECT user_id, points, level FROM user_levels ORDER BY points DESC LIMIT ?", (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

# ===================== نظام النقاط المتقدم =====================
async def daily_reward(user_id: int) -> int:
    """مكافأة يومية"""
    today = utc_now().date()
    async def _check(conn):
        cur = await conn.execute("SELECT last_daily_reward FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row[0]:
            try:
                last_date = datetime.fromisoformat(row[0]).date()
                if last_date == today:
                    return 0
            except:
                pass
        await conn.execute("UPDATE users SET last_daily_reward=? WHERE user_id=?", (utc_now_iso(), user_id))
        await conn.commit()
        return 10
    reward = await execute_db(_check)
    if reward > 0:
        data = await db_get_user_level(user_id)
        await db_update_user_level(user_id, data['points'] + reward, data['level'])
    return reward

async def weekly_reward(user_id: int) -> int:
    """مكافأة أسبوعية"""
    week_start = (utc_now() - timedelta(days=utc_now().weekday())).date()
    async def _check(conn):
        cur = await conn.execute("SELECT last_weekly_reward FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row[0]:
            try:
                last_date = datetime.fromisoformat(row[0]).date()
                if last_date >= week_start:
                    return 0
            except:
                pass
        await conn.execute("UPDATE users SET last_weekly_reward=? WHERE user_id=?", (utc_now_iso(), user_id))
        await conn.commit()
        return 50
    reward = await execute_db(_check)
    if reward > 0:
        data = await db_get_user_level(user_id)
        await db_update_user_level(user_id, data['points'] + reward, data['level'])
    return reward

# ===================== نظام الإنجازات =====================
ACHIEVEMENTS = {
    'first_post': {'name': 'أول منشور', 'points': 10, 'icon': '📝'},
    'first_week': {'name': 'أسبوع نشاط', 'points': 50, 'icon': '📅'},
    'first_month': {'name': 'شهر نشاط', 'points': 200, 'icon': '🎉'},
    'first_referral': {'name': 'أول إحالة', 'points': 25, 'icon': '🔗'},
    'ten_referrals': {'name': '10 إحالات', 'points': 100, 'icon': '🌟'},
    'first_contest': {'name': 'أول مسابقة', 'points': 30, 'icon': '🏆'},
    'contest_winner': {'name': 'فائز بمسابقة', 'points': 100, 'icon': '🥇'},
}

async def achievement_system(user_id: int, action: str) -> str:
    """نظام الإنجازات"""
    async def _get_achievements(conn):
        cur = await conn.execute("SELECT achievements FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else '[]'

    achievements = json.loads(await execute_db(_get_achievements) or '[]')

    if action == 'first_post' and 'first_post' not in achievements:
        achievements.append('first_post')
        await db_update_user_level(user_id, (await db_get_user_level(user_id))['points'] + ACHIEVEMENTS['first_post']['points'], 1)
        return f"{ACHIEVEMENTS['first_post']['icon']} {ACHIEVEMENTS['first_post']['name']} (+{ACHIEVEMENTS['first_post']['points']} نقطة)"

    if action == 'first_referral' and 'first_referral' not in achievements:
        achievements.append('first_referral')
        await db_update_user_level(user_id, (await db_get_user_level(user_id))['points'] + ACHIEVEMENTS['first_referral']['points'], 1)
        return f"{ACHIEVEMENTS['first_referral']['icon']} {ACHIEVEMENTS['first_referral']['name']} (+{ACHIEVEMENTS['first_referral']['points']} نقطة)"

    return ""

# ===================== دوال الإعدادات العامة =====================
async def db_get_publish_interval() -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='publish_interval'")
        row = await cur.fetchone()
        return int(row[0]) if row else DEFAULT_PUBLISH_INTERVAL_SECONDS
    return await execute_db(_get)

async def db_get_publish_interval_seconds() -> int:
    return await db_get_publish_interval()

async def db_set_publish_interval_seconds(seconds: int, admin_id: int, is_admin: bool = False):
    if not is_admin and admin_id != PRIMARY_OWNER_ID:
        return False
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('publish_interval', ?)", (str(seconds),))
        await conn.commit()
    await execute_db(_set)
    return True

async def db_get_updates_channel():
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='updates_channel'")
        row = await cur.fetchone()
        if row and row[0]:
            channel = row[0].strip()
            if channel.startswith('@'):
                channel = channel[1:]
            return channel if channel else None
        return None
    return await execute_db(_get)

async def db_set_updates_channel(channel: str):
    if not channel:
        return False
    channel = channel.strip()
    if channel.startswith('@'):
        channel = channel[1:]
    if not channel:
        return False
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('updates_channel', ?)", (channel,))
        await conn.commit()
    await execute_db(_set)
    logger.info(f"✅ تم حفظ قناة التحديثات: {channel}")
    return True

async def db_get_force_subscribe_status() -> bool:
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='force_subscribe_enabled'")
        row = await cur.fetchone()
        return row and row[0] == '1'
    return await execute_db(_get)

async def db_set_force_subscribe_status(enabled: bool):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('force_subscribe_enabled', ?)", ('1' if enabled else '0',))
        await conn.commit()
    return await execute_db(_set)

async def db_get_force_subscribe_channel():
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='force_subscribe_channel'")
        row = await cur.fetchone()
        return row[0] if row and row[0] else None
    return await execute_db(_get)

async def db_set_force_subscribe_channel(channel: str):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('force_subscribe_channel', ?)", (channel,))
        await conn.commit()
    return await execute_db(_set)

async def db_get_log_channel_id():
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='log_channel_id'")
        row = await cur.fetchone()
        return row[0] if row and row[0] else None
    return await execute_db(_get)

async def db_set_log_channel_id(channel_id: str):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('log_channel_id', ?)", (channel_id,))
        await conn.commit()
    return await execute_db(_set)

async def db_get_auto_backup() -> bool:
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='auto_backup'")
        row = await cur.fetchone()
        return row and row[0] == '1'
    return await execute_db(_get)

async def db_set_auto_backup(enabled: bool) -> None:
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('auto_backup', ?)", ('1' if enabled else '0',))
        await conn.commit()
    return await execute_db(_set)

async def db_get_last_backup_time():
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='last_backup'")
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_get_allowed_sendcode_user() -> int | None:
    async def _get(conn):
        cur = await conn.execute("SELECT user_id FROM allowed_sendcode_user WHERE id=1")
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_set_allowed_sendcode_user(user_id: int) -> None:
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO allowed_sendcode_user (id, user_id) VALUES (1, ?)", (user_id,))
        await conn.commit()
    return await execute_db(_set)
# ===================== دوال المسابقات =====================
class ContestTypes(Enum):
    QUIZ = "quiz"
    RAFFLE = "raffle"
    VOTE = "vote"
    SUBMISSION = "submission"

async def db_get_active_contests_with_participants(limit: int = 10) -> list:
    try:
        async def _get(conn):
            now = utc_now().isoformat()
            try:
                cur = await conn.execute(
                    """SELECT c.id, c.title, c.description, c.prize, c.end_date, c.contest_type,
                              COALESCE((SELECT COUNT(*) FROM contest_participants cp WHERE cp.contest_id = c.id), 0) as participants
                       FROM contests c
                       WHERE c.status = 'active' AND c.end_date > ?
                       ORDER BY c.end_date ASC LIMIT ?""",
                    (now, limit)
                )
                rows = await cur.fetchall()
                result = []
                for row in rows:
                    try:
                        if hasattr(row, 'keys'):
                            result.append((
                                row['id'],
                                row['title'],
                                row['description'],
                                row['prize'],
                                row['end_date'],
                                row['participants'],
                                row['contest_type'] if 'contest_type' in row else 'raffle'
                            ))
                        else:
                            result.append((row[0], row[1], row[2], row[3], row[4], row[5] if len(row) > 5 else 0, row[6] if len(row) > 6 else 'raffle'))
                    except:
                        continue
                return result
            except Exception as e:
                logger.error(f"خطأ في تنفيذ الاستعلام: {e}")
                return []
        return await execute_db(_get)
    except Exception as e:
        logger.error(f"خطأ في db_get_active_contests_with_participants: {e}")
        return []

async def db_create_contest(creator_id: int, title: str, description: str, prize: str, end_date: datetime, contest_type: str = 'raffle') -> int:
    try:
        async def _create(conn):
            if not isinstance(end_date, datetime):
                raise ValueError("end_date must be datetime object")
            end_date_str = end_date.isoformat()
            created_at_str = utc_now_iso()
            cur = await conn.execute(
                """INSERT INTO contests (creator_id, title, description, prize, end_date, status, created_at, contest_type)
                   VALUES (?, ?, ?, ?, ?, 'active', ?, ?) RETURNING id""",
                (creator_id, title, description, prize, end_date_str, created_at_str, contest_type)
            )
            row = await cur.fetchone()
            await conn.commit()
            return row[0] if row else None
        contest_id = await execute_db(_create)
        if contest_id:
            logger.info(f"✅ تم إنشاء مسابقة جديدة (ID: {contest_id}) بواسطة المستخدم {creator_id}")
        else:
            logger.warning(f"⚠️ فشل إنشاء المسابقة، لم يتم إرجاع ID للمستخدم {creator_id}")
        return contest_id
    except Exception as e:
        logger.error(f"❌ خطأ في db_create_contest: {e}")
        raise

async def db_get_contest(contest_id: int) -> dict | None:
    async def _get(conn):
        cur = await conn.execute(
            """SELECT id, title, description, prize, end_date, status, winner_id, creator_id, created_at, contest_type
               FROM contests WHERE id = ?""",
            (contest_id,)
        )
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
            await conn.execute(
                "INSERT INTO contest_participants (user_id, contest_id, answer, joined_at) VALUES (?, ?, ?, ?)",
                (user_id, contest_id, answer, utc_now_iso())
            )
            await conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    return await execute_db(_participate)

async def db_get_user_participation(user_id: int, contest_id: int) -> dict | None:
    async def _get(conn):
        cur = await conn.execute(
            "SELECT id, answer, joined_at FROM contest_participants WHERE user_id = ? AND contest_id = ?",
            (user_id, contest_id)
        )
        row = await cur.fetchone()
        if row:
            return {'id': row[0], 'answer': row[1], 'joined_at': row[2]}
        return None
    return await execute_db(_get)

async def db_set_contest_winner(contest_id: int, winner_id: int) -> bool:
    async def _set(conn):
        await conn.execute(
            "UPDATE contests SET status = 'finished', winner_id = ? WHERE id = ?",
            (winner_id, contest_id)
        )
        await conn.execute(
            "INSERT INTO contest_winners (contest_id, winner_id, announced_at) VALUES (?, ?, ?)",
            (contest_id, winner_id, utc_now_iso())
        )
        await conn.commit()
        return True
    return await execute_db(_set)

async def db_get_contest_winners(limit: int = 10) -> list:
    async def _get(conn):
        cur = await conn.execute(
            """SELECT c.id, c.title, c.prize, cw.winner_id, cw.announced_at
               FROM contest_winners cw
               JOIN contests c ON cw.contest_id = c.id
               ORDER BY cw.announced_at DESC LIMIT ?""",
            (limit,)
        )
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
        cur = await conn.execute(
            "SELECT user_id FROM contest_participants WHERE contest_id = ? ORDER BY RANDOM() LIMIT 1",
            (contest_id,)
        )
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def auto_grade_contest(contest_id: int, answer_key: str) -> dict:
    async def _get_participants(conn):
        cur = await conn.execute(
            "SELECT user_id, answer FROM contest_participants WHERE contest_id = ?",
            (contest_id,)
        )
        return await cur.fetchall()

    participants = await execute_db(_get_participants)
    results = {}
    for user_id, answer in participants:
        score = 0
        if answer and answer_key:
            if answer.lower() == answer_key.lower():
                score = 100
            else:
                similarity = len(set(answer.lower().split()) & set(answer_key.lower().split()))
                if similarity > 0:
                    score = min(100, similarity * 20)
        results[user_id] = score

    if results:
        winner = max(results, key=results.get)
        if results[winner] > 0:
            await db_set_contest_winner(contest_id, winner)
            return {'winner': winner, 'score': results[winner], 'total_participants': len(participants)}

    return {'winner': None, 'score': 0, 'total_participants': len(participants)}

# ===================== دوال إحصائيات القنوات =====================
async def db_get_channel_stats(channel_db_id: int) -> dict:
    async def _get_stats(conn):
        cur = await conn.execute(
            """
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
            """,
            (channel_db_id,)
        )
        row = await cur.fetchone()
        if not row or row[0] == 0:
            return {
                'total_posts': 0,
                'published_posts': 0,
                'unpublished_posts': 0,
                'total_views': 0,
                'avg_views': 0,
                'last_post_time': None,
                'first_post_time': None,
                'avg_time_between_posts': 0,
                'best_publish_hour': 0,
                'best_publish_day': 0,
                'published_today': 0,
                'published_this_week': 0,
                'published_this_month': 0,
                'most_viewed_post': None,
                'least_viewed_post': None,
            }
        total_posts = row[0] or 0
        published_posts = row[1] or 0
        unpublished_posts = row[2] or 0
        total_views = row[3] or 0
        avg_views = row[4] or 0
        last_post_time = row[5]
        first_post_time = row[6]
        avg_time_between = 0
        if published_posts > 1 and last_post_time and first_post_time:
            try:
                last_dt = datetime.fromisoformat(last_post_time)
                first_dt = datetime.fromisoformat(first_post_time)
                time_diff = (last_dt - first_dt).total_seconds()
                avg_time_between = time_diff / (published_posts - 1) if published_posts > 1 else 0
            except:
                avg_time_between = 0
        best_hour = 0
        best_day = 0
        if published_posts > 0:
            cur = await conn.execute(
                """
                SELECT
                    strftime('%H', created_at) as hour,
                    COUNT(*) as count
                FROM posts
                WHERE channel_db_id = ? AND published = 1
                GROUP BY hour
                ORDER BY count DESC
                LIMIT 1
                """,
                (channel_db_id,)
            )
            hour_row = await cur.fetchone()
            if hour_row:
                best_hour = int(hour_row[0])
            cur = await conn.execute(
                """
                SELECT
                    strftime('%w', created_at) as day,
                    COUNT(*) as count
                FROM posts
                WHERE channel_db_id = ? AND published = 1
                GROUP BY day
                ORDER BY count DESC
                LIMIT 1
                """,
                (channel_db_id,)
            )
            day_row = await cur.fetchone()
            if day_row:
                best_day = int(day_row[0])
        today = utc_now().date().isoformat()
        week_start = (utc_now() - timedelta(days=7)).isoformat()
        month_start = (utc_now() - timedelta(days=30)).isoformat()
        cur = await conn.execute(
            """
            SELECT
                SUM(CASE WHEN date(created_at) = ? THEN 1 ELSE 0 END) as today_count,
                SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as week_count,
                SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as month_count
            FROM posts
            WHERE channel_db_id = ? AND published = 1
            """,
            (today, week_start, month_start, channel_db_id)
        )
        extra_row = await cur.fetchone()
        published_today = extra_row[0] or 0 if extra_row else 0
        published_this_week = extra_row[1] or 0 if extra_row else 0
        published_this_month = extra_row[2] or 0 if extra_row else 0
        most_viewed = None
        least_viewed = None
        cur = await conn.execute(
            """
            SELECT id, text, views_count
            FROM posts
            WHERE channel_db_id = ? AND published = 1
            ORDER BY views_count DESC
            LIMIT 1
            """,
            (channel_db_id,)
        )
        most_row = await cur.fetchone()
        if most_row:
            most_viewed = {'id': most_row[0], 'text': most_row[1][:50] + '...' if most_row[1] and len(most_row[1]) > 50 else most_row[1], 'views': most_row[2]}
        cur = await conn.execute(
            """
            SELECT id, text, views_count
            FROM posts
            WHERE channel_db_id = ? AND published = 1 AND views_count > 0
            ORDER BY views_count ASC
            LIMIT 1
            """,
            (channel_db_id,)
        )
        least_row = await cur.fetchone()
        if least_row:
            least_viewed = {'id': least_row[0], 'text': least_row[1][:50] + '...' if least_row[1] and len(least_row[1]) > 50 else least_row[1], 'views': least_row[2]}
        return {
            'total_posts': total_posts,
            'published_posts': published_posts,
            'unpublished_posts': unpublished_posts,
            'total_views': total_views,
            'avg_views': round(avg_views, 2) if avg_views else 0,
            'last_post_time': last_post_time,
            'first_post_time': first_post_time,
            'avg_time_between_posts': round(avg_time_between / 3600, 2) if avg_time_between else 0,
            'best_publish_hour': best_hour,
            'best_publish_day': best_day,
            'published_today': published_today,
            'published_this_week': published_this_week,
            'published_this_month': published_this_month,
            'most_viewed_post': most_viewed,
            'least_viewed_post': least_viewed,
        }
    return await execute_db(_get_stats)

async def db_get_channel_stats_summary(user_id: int) -> dict:
    async def _get_summary(conn):
        channels = await db_get_channels(user_id)
        if not channels:
            return None
        total_posts = 0
        total_published = 0
        total_views = 0
        total_channels = len(channels)
        best_channel = None
        best_channel_views = 0
        active_channels = 0
        for ch_db_id, ch_tele_id, ch_name, banned in channels:
            if not banned:
                active_channels += 1
            stats = await db_get_channel_stats(ch_db_id)
            if stats and stats['total_posts'] > 0:
                total_posts += stats['total_posts']
                total_published += stats['published_posts']
                total_views += stats['total_views']
                if stats['total_views'] > best_channel_views:
                    best_channel_views = stats['total_views']
                    best_channel = {
                        'name': ch_name,
                        'views': stats['total_views'],
                        'posts': stats['published_posts'],
                        'avg_views': stats['avg_views']
                    }
        return {
            'total_channels': total_channels,
            'active_channels': active_channels,
            'total_posts': total_posts,
            'total_published': total_published,
            'total_views': total_views,
            'avg_views_per_channel': round(total_views / total_channels, 2) if total_channels > 0 else 0,
            'best_channel': best_channel
        }
    return await execute_db(_get_summary)

async def db_get_channel_growth(channel_db_id: int, days: int = 30) -> dict:
    async def _get_growth(conn):
        start_date = (utc_now() - timedelta(days=days)).isoformat()
        cur = await conn.execute(
            """
            SELECT
                date(created_at) as post_date,
                COUNT(*) as count,
                SUM(views_count) as views
            FROM posts
            WHERE channel_db_id = ? AND created_at >= ?
            GROUP BY date(created_at)
            ORDER BY post_date
            """,
            (channel_db_id, start_date)
        )
        rows = await cur.fetchall()
        dates = []
        counts = []
        views = []
        for row in rows:
            dates.append(row[0])
            counts.append(row[1] or 0)
            views.append(row[2] or 0)
        return {
            'dates': dates,
            'counts': counts,
            'views': views,
            'total_days': len(dates),
            'total_posts': sum(counts),
            'total_views': sum(views)
        }
    return await execute_db(_get_growth)

# ===================== دوال الصحة =====================
async def check_database_health() -> bool:
    try:
        async def _check(conn):
            cur = await conn.execute("SELECT 1")
            row = await cur.fetchone()
            return row is not None
        return await execute_db(_check)
    except:
        return False

async def check_telegram_health() -> bool:
    try:
        from telegram.ext import Application
        app = Application.builder().token(TOKEN).build()
        me = await app.bot.get_me()
        return me is not None
    except:
        return False

def get_ram_usage():
    try:
        import psutil
        mem = psutil.virtual_memory()
        return {
            'total': round(mem.total / (1024**3), 1),
            'used': round(mem.used / (1024**3), 1),
            'percent': mem.percent
        }
    except:
        try:
            with open('/proc/meminfo', 'r') as f:
                lines = f.readlines()
            mem_total = 0
            mem_available = 0
            for line in lines:
                if 'MemTotal:' in line:
                    mem_total = int(line.split()[1]) / (1024 * 1024)
                if 'MemAvailable:' in line:
                    mem_available = int(line.split()[1]) / (1024 * 1024)
            if mem_total > 0:
                used = mem_total - mem_available
                percent = (used / mem_total) * 100
                return {'total': round(mem_total, 1), 'used': round(used, 1), 'percent': round(percent, 1)}
        except:
            pass
        return {'total': 0, 'used': 0, 'percent': 0}

# ===================== دوال مساعدة =====================
def parse_days_of_week_safe(days_str):
    if not days_str:
        return []
    try:
        return json.loads(days_str)
    except:
        return []

def parse_dates_safe(dates_str):
    if not dates_str:
        return []
    try:
        return json.loads(dates_str)
    except:
        return []

def contains_link(text):
    patterns = [
        r'https?://\S+',
        r'www\.\S+',
        r't\.me/\S+',
        r'telegram\.me/\S+',
        r'\b[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)+\S*'
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)

def contains_mention(text):
    return bool(re.search(r'@\w+', text))

async def invalidate_user_cache(user_id: int):
    try:
        if user_id in _admin_cache:
            del _admin_cache[user_id]
        keys_to_remove = [k for k in _admin_cache.keys() if str(user_id) in k]
        for key in keys_to_remove:
            del _admin_cache[key]
    except:
        pass

async def cleanup_points_cache():
    while True:
        await asyncio.sleep(3600)
        user_points_last_hour.clear()

# ===================== دوال النسخ الاحتياطي =====================
async def create_backup():
    try:
        encrypted_path = encrypt_db_backup()
        temp_backup = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        temp_backup.close()
        shutil.copy2(DB_PATH, temp_backup.name)
        with open(temp_backup.name, 'rb') as f:
            backup_data = f.read()
        compressed = compress_backup(backup_data)
        encrypted = BACKUP_CIPHER.encrypt(compressed)
        backup_file = BACKUP_DIR / f"backup_{mecca_now().strftime('%Y%m%d_%H%M%S')}.enc"
        with open(backup_file, 'wb') as f:
            f.write(encrypted)
        os.unlink(temp_backup.name)
        backups = sorted(BACKUP_DIR.glob("backup_*.enc"), key=lambda x: x.stat().st_mtime, reverse=True)
        for old_backup in backups[MAX_BACKUPS:]:
            old_backup.unlink()
        if CLOUD_BACKUP_ENABLED and GOOGLE_AUTH_AVAILABLE:
            await upload_backup_to_drive(backup_file)
        logger.info(f"✅ تم إنشاء نسخة احتياطية مشفرة: {backup_file}")
        return backup_file
    except Exception as e:
        logger.error(f"❌ فشل إنشاء النسخة الاحتياطية: {e}")
        raise

async def incremental_backup():
    try:
        last_backup = await db_get_last_backup_time()
        if last_backup:
            last_time = datetime.fromisoformat(last_backup)
        else:
            last_time = utc_now() - timedelta(days=7)

        backup_data = {}

        async def _get_new_posts(conn):
            cur = await conn.execute(
                "SELECT * FROM posts WHERE created_at > ? LIMIT 1000",
                (last_time.isoformat(),)
            )
            return await cur.fetchall()

        new_posts = await execute_db(_get_new_posts)
        if new_posts:
            backup_data['posts'] = [dict(post) for post in new_posts]

        async def _get_new_users(conn):
            cur = await conn.execute(
                "SELECT * FROM users WHERE user_id IN (SELECT user_id FROM users_cache WHERE last_updated > ?)",
                (last_time.isoformat(),)
            )
            return await cur.fetchall()

        new_users = await execute_db(_get_new_users)
        if new_users:
            backup_data['users'] = [dict(user) for user in new_users]

        if backup_data:
            data_json = json.dumps(backup_data, default=str)
            compressed = compress_backup(data_json.encode('utf-8'))
            encrypted = BACKUP_CIPHER.encrypt(compressed)
            backup_file = BACKUP_DIR / f"incremental_{mecca_now().strftime('%Y%m%d_%H%M%S')}.inc"
            with open(backup_file, 'wb') as f:
                f.write(encrypted)
            logger.info(f"✅ تم إنشاء نسخة احتياطية متزايدة: {backup_file}")
            return backup_file

        logger.info("📭 لا توجد بيانات جديدة للنسخ الاحتياطي المتزايد")
        return None
    except Exception as e:
        logger.error(f"❌ فشل إنشاء النسخة الاحتياطية المتزايدة: {e}")
        return None

async def list_backups():
    backups = sorted(BACKUP_DIR.glob("backup_*.enc"), key=lambda x: x.stat().st_mtime, reverse=True)
    incremental = sorted(BACKUP_DIR.glob("incremental_*.inc"), key=lambda x: x.stat().st_mtime, reverse=True)
    return backups + incremental

async def restore_backup(backup_path: Path):
    if not backup_path.exists():
        raise FileNotFoundError(f"الملف {backup_path} غير موجود")
    with open(backup_path, 'rb') as f:
        encrypted = f.read()
    try:
        decrypted = BACKUP_CIPHER.decrypt(encrypted)
    except Exception as e:
        raise ValueError(f"فشل فك التشفير: {e}")
    try:
        decompressed = decompress_backup(decrypted)
    except Exception as e:
        raise ValueError(f"فشل فك الضغط: {e}")

    if backup_path.suffix == '.inc':
        data = json.loads(decompressed.decode('utf-8'))
        async def _merge_data(conn):
            if 'posts' in data:
                for post in data['posts']:
                    await conn.execute(
                        "INSERT OR IGNORE INTO posts (id, channel_db_id, text, media_type, media_file_id, published, fail_count, views_count, last_view_time, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (post['id'], post['channel_db_id'], post['text'], post['media_type'], post['media_file_id'], post['published'], post['fail_count'], post['views_count'], post['last_view_time'], post['created_at'])
                    )
            if 'users' in data:
                for user in data['users']:
                    await conn.execute(
                        "INSERT OR IGNORE INTO users (user_id, auto_publish, banned, trial_used, subscription_end, referral_code, referred_by, active_channel, auto_reply_enabled, auto_recycle) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (user['user_id'], user['auto_publish'], user['banned'], user['trial_used'], user['subscription_end'], user['referral_code'], user['referred_by'], user['active_channel'], user['auto_reply_enabled'], user['auto_recycle'])
                    )
            await conn.commit()
        await execute_db(_merge_data)
        logger.info(f"✅ تم دمج النسخة المتزايدة: {backup_path}")
    else:
        temp_restore = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        temp_restore.write(decompressed)
        temp_restore.close()
        current_backup = BACKUP_DIR / f"pre_restore_{mecca_now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(DB_PATH, current_backup)
        shutil.copy2(temp_restore.name, DB_PATH)
        os.unlink(temp_restore.name)
        await db_pool.initialize()
        logger.info(f"✅ تم استعادة النسخة الكاملة: {backup_path}")

async def auto_backup():
    consecutive_errors = 0
    backoff = AUTO_BACKUP_SLEEP
    max_backoff = 7 * 24 * 60 * 60
    while True:
        try:
            await asyncio.sleep(AUTO_BACKUP_SLEEP)
            auto_enabled = await db_get_auto_backup()
            if auto_enabled:
                last_backup = await db_get_last_backup_time()
                if not last_backup:
                    await create_backup()
                else:
                    last_time = datetime.fromisoformat(last_backup)
                    if (utc_now() - last_time).days >= 7:
                        await create_backup()
                    else:
                        await incremental_backup()
                async def _update_backup_time(conn):
                    await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('last_backup', ?)", (utc_now_iso(),))
                    await conn.commit()
                await execute_db(_update_backup_time)
            consecutive_errors = 0
            backoff = AUTO_BACKUP_SLEEP
        except Exception as e:
            logger.error(f"⚠️ خطأ في النسخ الاحتياطي التلقائي: {e}")
            backoff = min(backoff * 1.5, max_backoff)
            await asyncio.sleep(backoff)

# ===================== دوال جوجل درايف =====================
_DRIVE_SERVICE_CACHE = None
_DRIVE_SERVICE_CACHE_TIME = 0
_DRIVE_SERVICE_CACHE_TTL = 3600

async def get_google_drive_service(force_refresh: bool = False):
    global _DRIVE_SERVICE_CACHE, _DRIVE_SERVICE_CACHE_TIME
    if not CLOUD_BACKUP_ENABLED or not GOOGLE_AUTH_AVAILABLE:
        logger.warning("☁️ Google Drive Backup معطل أو غير مدعوم")
        return None
    now = time_module.time()
    if not force_refresh and _DRIVE_SERVICE_CACHE and (now - _DRIVE_SERVICE_CACHE_TIME) < _DRIVE_SERVICE_CACHE_TTL:
        return _DRIVE_SERVICE_CACHE
    try:
        creds = None
        token_path = Path(TOKEN_FILE)
        if token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(token_path),
                                                              ['https://www.googleapis.com/auth/drive.file'])
            except Exception as e:
                logger.warning(f"⚠️ فشل تحميل التوكن المخزن: {e}")
        if creds and creds.valid:
            _DRIVE_SERVICE_CACHE = build('drive', 'v3', credentials=creds)
            _DRIVE_SERVICE_CACHE_TIME = now
            logger.info("✅ تم استعادة خدمة Google Drive من التوكن المخزن")
            return _DRIVE_SERVICE_CACHE
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(token_path, 'w') as token:
                    token.write(creds.to_json())
                _DRIVE_SERVICE_CACHE = build('drive', 'v3', credentials=creds)
                _DRIVE_SERVICE_CACHE_TIME = now
                logger.info("✅ تم تجديد توكن Google Drive")
                return _DRIVE_SERVICE_CACHE
            except Exception as e:
                logger.warning(f"⚠️ فشل تجديد التوكن: {e}")
                if token_path.exists():
                    token_path.unlink()
        if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
            logger.error(f"❌ ملف الاعتمادات غير موجود: {GOOGLE_CREDENTIALS_FILE}")
            return None
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(
            GOOGLE_CREDENTIALS_FILE,
            ['https://www.googleapis.com/auth/drive.file']
        )
        creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
        _DRIVE_SERVICE_CACHE = build('drive', 'v3', credentials=creds)
        _DRIVE_SERVICE_CACHE_TIME = now
        logger.info("✅ تم الحصول على توكن Google Drive جديد")
        return _DRIVE_SERVICE_CACHE
    except Exception as e:
        logger.error(f"❌ خطأ في خدمة Google Drive: {e}")
        return None

async def upload_backup_to_drive(backup_path: Path, max_retries: int = 3) -> str:
    if not CLOUD_BACKUP_ENABLED or not GOOGLE_AUTH_AVAILABLE or not GOOGLE_DRIVE_FOLDER_ID:
        return None
    if not backup_path.exists():
        logger.error(f"❌ ملف النسخ غير موجود: {backup_path}")
        return None
    for attempt in range(max_retries):
        try:
            service = await get_google_drive_service(force_refresh=(attempt > 0))
            if not service:
                if attempt == max_retries - 1:
                    logger.error("❌ فشل الحصول على خدمة Google Drive بعد عدة محاولات")
                    return None
                await asyncio.sleep(2 ** attempt)
                continue
            file_name = f"backup_{mecca_now().strftime('%Y%m%d_%H%M%S')}.enc"
            try:
                results = service.files().list(
                    q=f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents",
                    orderBy="createdTime desc",
                    pageSize=15,
                    fields="files(id, name)"
                ).execute()
                files = results.get('files', [])
                for old_file in files[10:]:
                    try:
                        service.files().delete(fileId=old_file['id']).execute()
                        logger.info(f"🗑️ تم حذف ملف قديم من Drive: {old_file['name']}")
                    except Exception as e:
                        logger.warning(f"⚠️ فشل حذف الملف القديم: {e}")
            except Exception as e:
                logger.warning(f"⚠️ فشل تنظيف الملفات القديمة: {e}")
            media = MediaFileUpload(
                str(backup_path),
                mimetype='application/octet-stream',
                resumable=True,
                chunksize=1024*1024
            )
            file_metadata = {
                'name': file_name,
                'parents': [GOOGLE_DRIVE_FOLDER_ID]
            }
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            )
            response = file.execute()
            file_id = response.get('id')
            logger.info(f"✅ تم رفع النسخة إلى Google Drive: {file_id} (المحاولة {attempt+1})")
            return file_id
        except Exception as e:
            logger.error(f"❌ خطأ في رفع النسخة: {e}")
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(2 ** attempt)
    return None

# ===================== دوال الأمان والإجراءات المتقدمة =====================
async def check_bot_admin_permissions(bot, chat_id: int) -> dict:
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
        if me.status not in ['administrator', 'creator']:
            return {'can_act': False, 'reason': 'البوت ليس مشرفاً'}
        permissions = {
            'can_ban': getattr(me, 'can_restrict_members', False),
            'can_pin': getattr(me, 'can_pin_messages', False),
            'can_delete': getattr(me, 'can_delete_messages', False),
        }
        missing = [k for k, v in permissions.items() if not v]
        if missing:
            return {'can_act': False, 'reason': f'البوت يحتاج صلاحيات: {", ".join(missing)}'}
        return {'can_act': True, 'reason': ''}
    except Exception as e:
        return {'can_act': False, 'reason': str(e)}

async def check_bot_permissions(bot, channel_id: str) -> tuple:
    try:
        me = await bot.get_chat_member(channel_id, bot.id)
        if me.status not in ['administrator', 'creator']:
            return False, "البوت ليس مشرفاً في القناة"
        if not me.can_post_messages:
            return False, "البوت لا يملك صلاحية النشر"
        return True, ""
    except Exception as e:
        return False, str(e)[:100]

async def apply_penalty(bot, chat_id, user_id, settings):
    penalty = settings.get('auto_penalty', 'none')
    if penalty == 'none':
        return
    if penalty == 'kick':
        await execute_kick(bot, chat_id, user_id, "مخالفة قواعد المجموعة")
    elif penalty == 'ban':
        await execute_ban(bot, chat_id, user_id, reason="مخالفة قواعد المجموعة")
    elif penalty == 'mute':
        duration = settings.get('auto_mute_duration', 60)
        await execute_mute(bot, chat_id, user_id, duration, "مخالفة قواعد المجموعة")

# ===================== دوال الإجراءات المتقدمة =====================
async def execute_ban(bot, chat_id: int, user_id: int, until_date=None, reason: str = "", moderator_id: int = None):
    try:
        await bot.ban_chat_member(chat_id, user_id, until_date=until_date)
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'ban', 0, ?, ?, ?)",
                              (chat_id, user_id, moderator_id or PRIMARY_OWNER_ID, reason[:200] if reason else "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم حظر المستخدم `{user_id}` بنجاح"
    except Exception as e:
        return False, f"❌ فشل الحظر: خطأ غير معروف"

async def execute_mute(bot, chat_id: int, user_id: int, duration_minutes: int = None, reason: str = "", moderator_id: int = None):
    try:
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
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'mute', ?, ?, ?, ?)",
                              (chat_id, user_id, duration_minutes, moderator_id or PRIMARY_OWNER_ID, reason[:200] if reason else "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم كتم المستخدم `{user_id}`{duration_text}"
    except Exception as e:
        return False, f"❌ فشل الكتم: خطأ غير معروف"

async def execute_kick(bot, chat_id: int, user_id: int, reason: str = "", moderator_id: int = None):
    try:
        await bot.ban_chat_member(chat_id, user_id)
        await bot.unban_chat_member(chat_id, user_id)
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'kick', 0, ?, ?, ?)",
                              (chat_id, user_id, moderator_id or PRIMARY_OWNER_ID, reason[:200] if reason else "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم طرد المستخدم `{user_id}`"
    except Exception as e:
        return False, f"❌ فشل الطرد: خطأ غير معروف"

async def execute_warn(bot, chat_id: int, user_id: int, moderator_id: int, reason: str = "", auto_ban_limit: int = 3):
    async def _add_warning(conn):
        cur = await conn.execute("SELECT warnings FROM user_warnings WHERE user_id=? AND chat_id=?", (user_id, chat_id))
        row = await cur.fetchone()
        warnings = row[0] + 1 if row else 1
        await conn.execute("INSERT OR REPLACE INTO user_warnings (user_id, chat_id, warnings) VALUES (?,?,?)", (user_id, chat_id, warnings))
        await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'warn', ?, ?, ?, ?)",
                          (chat_id, user_id, warnings, moderator_id, reason[:200] if reason else "", utc_now_iso()))
        await conn.commit()
        return warnings
    warnings = await execute_db(_add_warning)
    if warnings >= auto_ban_limit:
        await execute_ban(bot, chat_id, user_id, reason=f"تلقائي بعد {warnings} تحذيرات", moderator_id=moderator_id)
        async def _clear_warnings(conn):
            await conn.execute("DELETE FROM user_warnings WHERE user_id=? AND chat_id=?", (user_id, chat_id))
            await conn.commit()
        await execute_db(_clear_warnings)
        return True, f"⚠️ تم تحذير المستخدم `{user_id}` ({warnings}/{auto_ban_limit}) وتم حظره تلقائياً"
    return True, f"⚠️ تم تحذير المستخدم `{user_id}` ({warnings}/{auto_ban_limit})"

async def execute_restrict(bot, chat_id: int, user_id: int, reason: str = "", moderator_id: int = None):
    try:
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False
        )
        await bot.restrict_chat_member(chat_id, user_id, permissions)
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'restrict', 0, ?, ?, ?)",
                              (chat_id, user_id, moderator_id or PRIMARY_OWNER_ID, reason[:200] if reason else "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم تقييد المستخدم `{user_id}` (لا يمكنه إرسال وسائط)"
    except Exception as e:
        return False, f"❌ فشل التقييد: خطأ غير معروف"

async def execute_pin(bot, chat_id: int, message_id: int, disable_notification: bool = False):
    try:
        await bot.pin_chat_message(chat_id, message_id, disable_notification=disable_notification)
        return True, "✅ تم تثبيت الرسالة"
    except Exception as e:
        return False, f"❌ فشل التثبيت: خطأ غير معروف"

async def execute_unban(bot, chat_id: int, user_id: int, moderator_id: int = None):
    try:
        await bot.unban_chat_member(chat_id, user_id)
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'unban', 0, ?, ?, ?)",
                              (chat_id, user_id, moderator_id or PRIMARY_OWNER_ID, "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم إلغاء حظر المستخدم `{user_id}`"
    except Exception as e:
        return False, f"❌ فشل إلغاء الحظر: خطأ غير معروف"

async def get_moderation_log(chat_id: int, limit: int = 20) -> str:
    async def _get_log(conn):
        cur = await conn.execute("""
            SELECT user_id, action, duration_minutes, reason, created_at
            FROM moderation_log
            WHERE chat_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (chat_id, limit))
        return await cur.fetchall()
    logs = await execute_db(_get_log)
    if not logs:
        return "📭 لا توجد سجلات إجراءات"
    text = "📜 **سجل إجراءات المجموعة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for user_id, action, duration, reason, created_at in logs:
        try:
            dt = datetime.fromisoformat(created_at)
            dt_mecca = utc_to_mecca(dt)
            time_str = dt_mecca.strftime("%Y-%m-%d %H:%M")
        except:
            time_str = created_at[:16] if created_at else "?"
        duration_text = ""
        if action == 'mute' and duration:
            if duration == -1:
                duration_text = " (دائم)"
            elif duration < 60:
                duration_text = f" ({duration} دقيقة)"
            elif duration < 1440:
                duration_text = f" ({duration//60} ساعة)"
            else:
                duration_text = f" ({duration//1440} يوم)"
        elif action == 'warn' and duration:
            duration_text = f" (تحذير #{duration})"
        elif action == 'unban':
            duration_text = ""
        reason_text = f"\n   📝 السبب: {reason[:50]}" if reason else ""
        text += f"• `{user_id}` → {action}{duration_text}{reason_text}\n   🕐 {time_str}\n\n"
    return text

# ===================== نظام جمع المقاييس =====================
class MetricsCollector:
    def __init__(self):
        self.commands_count = defaultdict(int)
        self.errors_count = defaultdict(int)
        self.response_times = []
        self.start_time = time_module.time()

    def record_command(self, command: str):
        self.commands_count[command] += 1

    def record_error(self, error_type: str):
        self.errors_count[error_type] += 1

    def record_response_time(self, seconds: float):
        self.response_times.append(seconds)
        if len(self.response_times) > 1000:
            self.response_times.pop(0)

    def get_stats(self) -> dict:
        avg_response = sum(self.response_times) / len(self.response_times) if self.response_times else 0
        return {
            'uptime': time_module.time() - self.start_time,
            'total_commands': sum(self.commands_count.values()),
            'commands': dict(self.commands_count),
            'errors': dict(self.errors_count),
            'avg_response_time': avg_response,
        }

metrics = MetricsCollector()

# ===================== دوال القوائم والأزرار (الكيبورد) =====================
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
        [InlineKeyboardButton("🎬 حذف الفيديوهات", callback_data=f"{CallbackData.SECURITY_DELETE_VIDEOS_PREFIX}{chat_id}"),
         InlineKeyboardButton("🛠️ حذف رسائل الخدمة", callback_data=f"{CallbackData.SECURITY_DELETE_SERVICE_PREFIX}{chat_id}")],
        [InlineKeyboardButton("📄 حذف الملفات", callback_data=f"{CallbackData.SECURITY_DELETE_DOCUMENTS_PREFIX}{chat_id}"),
         InlineKeyboardButton("🖼️ حذف الملصقات", callback_data=f"{CallbackData.SECURITY_DELETE_STICKERS_PREFIX}{chat_id}")],
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

async def build_days_keyboard(uid, context):
    selected = context.user_data.get('selected_days', [])
    day_names = [get_text(uid, 'monday'), get_text(uid, 'tuesday'), get_text(uid, 'wednesday'),
                 get_text(uid, 'thursday'), get_text(uid, 'friday'), get_text(uid, 'saturday'),
                 get_text(uid, 'sunday')]
    kb_buttons = []
    for i in range(0, 7, 3):
        row = []
        for j in range(3):
            if i + j < 7:
                day_index = i + j
                name = day_names[day_index]
                mark = "✅ " if day_index in selected else ""
                row.append(InlineKeyboardButton(f"{mark}{name}", callback_data=f"{CallbackData.SCHEDULE_DAY_SELECT_PREFIX}{day_index}"))
        if row:
            kb_buttons.append(row)
    kb_buttons.append([
        [InlineKeyboardButton("✔️ حفظ", callback_data=CallbackData.SCHEDULE_SAVE_DAYS),
         InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    return InlineKeyboardMarkup(kb_buttons)

# ===================== دالة get_main_keyboard =====================
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
    title = get_text(user_id, 'main_title').format(BOT_NAME, user_id, my_groups, sub_text, ch_display, cnt, auto_status)
    updates_channel = None
    try:
        updates_channel = await db_get_updates_channel()
    except:
        updates_channel = None
    updates_url = f"https://t.me/{updates_channel}" if updates_channel else None
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
    if updates_url:
        keyboard.append([
            InlineKeyboardButton(get_text(user_id, 'updates_btn'), callback_data=CallbackData.UPDATES)
        ])
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'add_to_group'), url=f"https://t.me/{BOT_USERNAME}?startgroup")
    ])
    is_admin = False
    try:
        is_admin = (user_id == PRIMARY_OWNER_ID) or (await is_bot_admin(user_id))
    except:
        is_admin = False
    if is_admin:
        keyboard.append([
            InlineKeyboardButton(get_text(user_id, 'admin_panel'), callback_data=CallbackData.ADMIN_PANEL)
        ])
    valid_keyboard = []
    for row in keyboard:
        if row and all(isinstance(btn, InlineKeyboardButton) for btn in row):
            valid_keyboard.append(row)
    if not valid_keyboard:
        valid_keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    return InlineKeyboardMarkup(valid_keyboard), title, active
# ===================== دالة معالجة حالات إنشاء المسابقات =====================
async def handle_contest_creation_states(update: Update, context: ContextTypes.DEFAULT_TYPE, state: UserState) -> bool:
    try:
        user_id = update.effective_user.id
        text = update.message.text.strip() if update.message.text else ""

        if state == UserState.WAITING_CONTEST_TITLE:
            if not text:
                await update.message.reply_text("❌ الرجاء إدخال عنوان صحيح.")
                return True
            context.user_data['contest_title'] = text
            context.user_data['state'] = UserState.WAITING_CONTEST_DESCRIPTION
            await update.message.reply_text("📝 أرسل وصف المسابقة:")
            return True

        elif state == UserState.WAITING_CONTEST_DESCRIPTION:
            if not text:
                await update.message.reply_text("❌ الرجاء إدخال وصف صحيح.")
                return True
            context.user_data['contest_description'] = text
            context.user_data['state'] = UserState.WAITING_CONTEST_PRIZE
            await update.message.reply_text("🎁 أرسل جائزة المسابقة:")
            return True

        elif state == UserState.WAITING_CONTEST_PRIZE:
            if not text:
                await update.message.reply_text("❌ الرجاء إدخال جائزة صحيحة.")
                return True
            context.user_data['contest_prize'] = text
            context.user_data['state'] = UserState.WAITING_CONTEST_END_DATE
            await update.message.reply_text("📅 أرسل تاريخ انتهاء المسابقة (صيغة: YYYY-MM-DD HH:MM) بتوقيت مكة:")
            return True

        elif state == UserState.WAITING_CONTEST_END_DATE:
            try:
                end_date = datetime.strptime(text, "%Y-%m-%d %H:%M")
                now_mecca = mecca_now()
                if end_date <= now_mecca:
                    await update.message.reply_text("❌ التاريخ يجب أن يكون في المستقبل!")
                    return True
                end_date_utc = mecca_to_utc(end_date)
                title = context.user_data.pop('contest_title', 'بدون عنوان')
                description = context.user_data.pop('contest_description', '')
                prize = context.user_data.pop('contest_prize', '')
                contest_type = context.user_data.pop('contest_type', 'raffle')
                contest_id = await db_create_contest(user_id, title, description, prize, end_date_utc, contest_type)
                if contest_id:
                    await update.message.reply_text(
                        f"✅ **تم إنشاء المسابقة بنجاح!**\n\n"
                        f"📌 العنوان: {title}\n"
                        f"🎁 الجائزة: {prize}\n"
                        f"📅 تنتهي: {end_date.strftime('%Y-%m-%d %H:%M')} (بتوقيت مكة)\n"
                        f"🆔 معرف المسابقة: `{contest_id}`"
                    )
                    try:
                        await context.bot.send_message(
                            PRIMARY_OWNER_ID,
                            f"🏆 تم إنشاء مسابقة جديدة بواسطة المستخدم {user_id}\nالعنوان: {title}"
                        )
                    except:
                        pass
                else:
                    await update.message.reply_text("❌ فشل إنشاء المسابقة، حاول مرة أخرى.")
            except ValueError:
                await update.message.reply_text("❌ صيغة تاريخ غير صحيحة!\nاستخدم: YYYY-MM-DD HH:MM")
                return True
            except Exception as e:
                error_id = log_error(e, {'user_id': user_id, 'action': 'create_contest', 'date_input': text})
                await update.message.reply_text(f"❌ حدث خطأ أثناء إنشاء المسابقة (الرمز: `{error_id}`).")
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
                await update.message.reply_text("✅ تم تسجيل مشاركتك في المسابقة بنجاح!")
                try:
                    level_data = await db_get_user_level(user_id)
                    await db_update_user_level(user_id, level_data['points'] + 5, level_data['level'])
                except:
                    pass
            else:
                await update.message.reply_text("❌ أنت مشترك بالفعل في هذه المسابقة!")
            context.user_data.pop('contest_join_id', None)
            context.user_data.pop('state', None)
            await contests_command_handler(update, context)
            return True

        return False
    except Exception as e:
        error_id = log_error(e, {'user_id': user_id, 'state': state.name if state else 'None'})
        await update.message.reply_text(f"❌ حدث خطأ غير متوقع (الرمز: `{error_id}`).")
        context.user_data.pop('state', None)
        return True

# ===================== معالجات الكولباك الأساسية =====================
async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    kb, title, active_channel = await get_main_keyboard(uid)
    if active_channel:
        context.user_data['active_channel'] = active_channel
        await db_set_active_channel(uid, active_channel)
    if query:
        await safe_edit_markdown(query, title, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, title, reply_markup=kb)

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await main_menu_callback(update, context)

async def cancel_session_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    context.user_data.pop(f"session_{uid}", None)
    context.user_data.pop(f"session_target_{uid}", None)
    context.user_data.pop('state', None)
    if query:
        await query.edit_message_text(get_text(uid, 'cancelled'))
    else:
        await context.bot.send_message(chat_id=uid, text=get_text(uid, 'cancelled'))
    await main_menu_callback(update, context)

async def add_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    context.user_data['state'] = UserState.WAITING_CHANNEL_ID
    msg = get_text(uid, 'send_channel_id')
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def my_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    channels = await db_get_channels(uid)
    if not channels:
        msg = get_text(uid, 'no_channels_list')
        if query:
            await query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return
    kb = []
    for ch in channels:
        ch_db_id, ch_tele_id, ch_name, banned = ch
        display = ch_name if ch_name != ch_tele_id else ch_tele_id
        kb.append([
            InlineKeyboardButton(f"📢 {display}", callback_data=f"{CallbackData.CHANNELS_SELECT_PREFIX}{ch_db_id}"),
            InlineKeyboardButton(get_text(uid, 'channel_stats'), callback_data=f"{CallbackData.CHANNEL_STATS}:{ch_db_id}"),
            InlineKeyboardButton(get_text(uid, 'delete_channel'), callback_data=f"{CallbackData.CHANNELS_DELETE_PREFIX}{ch_db_id}")
        ])
    kb.append([InlineKeyboardButton(get_text(uid, 'add_channel'), callback_data=CallbackData.CHANNELS_ADD)])
    kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)])
    if query:
        await query.edit_message_text(get_text(uid, 'channels_list'), reply_markup=InlineKeyboardMarkup(kb))
    else:
        await safe_send_markdown(context.bot, uid, get_text(uid, 'channels_list'), reply_markup=InlineKeyboardMarkup(kb))

async def delete_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('delete_channel_id')
    if not ch_db_id:
        return
    if await db_delete_channel_by_id(uid, ch_db_id):
        if query:
            await query.edit_message_text(get_text(uid, 'channel_deleted'))
        else:
            await update.message.reply_text(get_text(uid, 'channel_deleted'))
        await my_channels_callback(update, context)
    else:
        if query:
            await query.answer(get_text(uid, 'delete_failed'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'delete_failed'))

async def select_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    await db_set_active_channel(uid, ch_db_id)
    context.user_data['active_channel'] = ch_db_id
    await invalidate_user_cache(uid)
    kb, title, new_active = await get_main_keyboard(uid)
    if new_active:
        context.user_data['active_channel'] = new_active
    if query:
        await safe_edit_markdown(query, title, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, title, reply_markup=kb)

async def add_15_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if not active:
        if query:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
        else:
            await update.message.reply_text("⚠️ اختر قناة أولاً")
        return
    unpublished_count = await db_unpublished_count(active)
    if unpublished_count >= MAX_UNPUBLISHED_POSTS:
        if query:
            await query.edit_message_text(f"⚠️ لقد تجاوزت الحد الأقصى للمنشورات غير المنشورة ({MAX_UNPUBLISHED_POSTS}).\nقم بنشر بعض المنشورات أولاً.")
        else:
            await update.message.reply_text(f"⚠️ لقد تجاوزت الحد الأقصى للمنشورات غير المنشورة ({MAX_UNPUBLISHED_POSTS}).\nقم بنشر بعض المنشورات أولاً.")
        return
    context.user_data[f"session_{uid}"] = []
    context.user_data[f"session_target_{uid}"] = min(15, MAX_UNPUBLISHED_POSTS - unpublished_count)
    context.user_data['state'] = UserState.ADDING_POSTS
    cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.CANCEL_SESSION)]])
    msg = f"📥 أرسل المنشورات (نصوص أو صور أو فيديوهات أو مستندات)\nالحد الأقصى المسموح: {MAX_UNPUBLISHED_POSTS - unpublished_count} منشور"
    if query:
        await query.edit_message_text(msg, reply_markup=cancel_kb)
    else:
        await update.message.reply_text(msg, reply_markup=cancel_kb)

async def publish_one_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if not active:
        if query:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
        else:
            await update.message.reply_text("⚠️ اختر قناة أولاً")
        return
    post = await db_get_next_post(active)
    if not post:
        if query:
            await query.edit_message_text(get_text(uid, 'no_posts'))
        else:
            await update.message.reply_text(get_text(uid, 'no_posts'))
        return
    ch_info = await db_get_channel_info(active)
    translation_lang = await get_user_translation_language(uid)
    final_text = post['text']
    if translation_lang != 'off' and final_text:
        try:
            translated = await translate_text(final_text, translation_lang)
            if translated and translated != final_text:
                final_text = f"{final_text}\n\n🌐 {translated}"
        except:
            pass
    try:
        if post['media_type'] == 'photo' and post['media_file_id']:
            await context.bot.send_photo(ch_info[0], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'video' and post['media_file_id']:
            await context.bot.send_video(ch_info[0], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'document' and post['media_file_id']:
            await context.bot.send_document(ch_info[0], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'audio' and post['media_file_id']:
            await context.bot.send_audio(ch_info[0], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'voice' and post['media_file_id']:
            await context.bot.send_voice(ch_info[0], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'animation' and post['media_file_id']:
            await context.bot.send_animation(ch_info[0], post['media_file_id'], caption=final_text if final_text else None)
        else:
            await context.bot.send_message(ch_info[0], final_text, parse_mode=None)
        await db_mark_published(post['id'])
        await db_set_last_publish(active, utc_now())
        await db_update_next_publish_date(active)
        if query:
            await query.edit_message_text("✅ تم نشر المنشور بنجاح!")
        else:
            await update.message.reply_text("✅ تم نشر المنشور بنجاح!")
    except Exception as e:
        error_id = log_error(e, {'user_id': uid, 'action': 'publish_one'})
        if query:
            await query.edit_message_text(f"❌ فشل النشر (الرمز: `{error_id}`)")
        else:
            await update.message.reply_text(f"❌ فشل النشر (الرمز: `{error_id}`)")
    await main_menu_callback(update, context)

async def my_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if not active:
        if query:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
        else:
            await update.message.reply_text("⚠️ اختر قناة أولاً")
        return
    posts = await db_get_user_posts_for_channel(active, limit=15)
    if not posts:
        if query:
            await query.edit_message_text(get_text(uid, 'no_posts'))
        else:
            await update.message.reply_text(get_text(uid, 'no_posts'))
        return
    msg = get_text(uid, 'my_posts_title') + "\n"
    kb_buttons = []
    for idx, (pid, ptext, media_type) in enumerate(posts[:10], 1):
        short = re.sub('<[^>]+>', '', ptext)[:80]
        media_icon = "🖼️" if media_type == 'photo' else "🎬" if media_type == 'video' else "📝" if media_type == 'text' else "📄"
        msg += f"{idx}. {media_icon} {short}...\n🆔 {pid}\n\n"
        kb_buttons.append([InlineKeyboardButton(f"🗑️ حذف #{pid}", callback_data=f"{CallbackData.POSTS_DELETE_SINGLE_PREFIX}{pid}_{active}")])
    kb_buttons.append([InlineKeyboardButton("🗑️ حذف الكل", callback_data=f"{CallbackData.POSTS_CONFIRM_CLEAR_ALL_PREFIX}{active}")])
    kb_buttons.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)])
    if query:
        await safe_edit_markdown(query, msg, reply_markup=InlineKeyboardMarkup(kb_buttons))
    else:
        await safe_send_markdown(context.bot, uid, msg, reply_markup=InlineKeyboardMarkup(kb_buttons))

async def delete_single_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    parts = query.data.split(":")[-1].split("_") if query else context.user_data.get('delete_post_data', '').split("_")
    if len(parts) >= 2:
        post_id = int(parts[0])
        active = int(parts[1])
        if await db_delete_single_post(post_id, uid, active):
            if query:
                await query.answer("✅ تم حذف المنشور", show_alert=True)
            else:
                await update.message.reply_text("✅ تم حذف المنشور")
            await my_posts_callback(update, context)
        else:
            if query:
                await query.answer("❌ فشل الحذف", show_alert=True)
            else:
                await update.message.reply_text("❌ فشل الحذف")

async def confirm_clear_all_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = int(query.data.split(":")[-1]) if query else context.user_data.get('clear_all_posts_id')
    if not active:
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم", callback_data=f"{CallbackData.POSTS_CLEAR_ALL_PREFIX}{active}"),
         InlineKeyboardButton("❌ لا", callback_data=CallbackData.BACK)]
    ])
    if query:
        await query.edit_message_text(get_text(uid, 'confirm_delete'), reply_markup=kb)
    else:
        await update.message.reply_text(get_text(uid, 'confirm_delete'), reply_markup=kb)

async def clear_all_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = int(query.data.split(":")[-1]) if query else context.user_data.get('clear_all_posts_id')
    if not active:
        return
    async def _clear_posts(conn):
        await conn.execute("DELETE FROM posts WHERE channel_db_id=?", (active,))
        await conn.commit()
    await execute_db(_clear_posts)
    if query:
        await query.answer(get_text(uid, 'deleted_all'), show_alert=True)
    else:
        await update.message.reply_text(get_text(uid, 'deleted_all'))
    await main_menu_callback(update, context)

async def recycle_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if active:
        await db_reset_posts_to_unpublished(active, uid)
        if query:
            await query.edit_message_text(get_text(uid, 'recycled'))
        else:
            await update.message.reply_text(get_text(uid, 'recycled'))
    else:
        if query:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
        else:
            await update.message.reply_text("⚠️ اختر قناة أولاً")
    await main_menu_callback(update, context)

async def my_pending_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    unpublished = await db_get_user_unpublished_posts(uid)
    total = await db_get_user_total_posts(uid)
    text = get_text(uid, 'pending_stats').format(unpublished, total)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def my_full_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    channels = await db_get_user_channels_count(uid)
    total = await db_get_user_total_posts(uid)
    unpublished = await db_get_user_unpublished_posts(uid)
    groups = await db_get_user_groups_count(uid)
    auto = get_text(uid, 'auto_on') if await db_auto_status(uid) else get_text(uid, 'auto_off')
    text = get_text(uid, 'stats').format(channels, total, unpublished, groups, auto)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def my_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id

    groups = await db_get_user_groups(uid)

    if not groups:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ أضف البوت", url=f"https://t.me/{BOT_USERNAME}?startgroup")],
            [InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS)],
            [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
        ])
        msg = "📭 لا توجد مجموعات مسجلة\n\nأضف البوت إلى مجموعة وستظهر هنا."
        if query:
            await safe_edit_markdown(query, msg, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, msg, reply_markup=kb)
        return

    keyboard = []
    for chat_id, chat_name, username, banned in groups:
        display_name = chat_name[:28] + "..." if len(chat_name) > 31 else chat_name
        status_icon = "⛔" if banned else "✅"
        keyboard.append([
            InlineKeyboardButton(
                f"{status_icon} {display_name}",
                callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}"
            )
        ])
        keyboard.append([
            InlineKeyboardButton("🔐 الأمان", callback_data=f"{CallbackData.SECURITY_SELECT_GROUP}{chat_id}"),
            InlineKeyboardButton("📜 السجل", callback_data=f"{CallbackData.GROUP_ACTION_LOG}:{chat_id}"),
            InlineKeyboardButton("⚙️ متقدم", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}")
        ])
        is_locked = await is_chat_locked(chat_id)
        lock_label = "🔒 قفل" if not is_locked else "🔓 فتح"
        lock_callback = f"{CallbackData.PANEL_LOCK_PREFIX}{chat_id}" if not is_locked else f"{CallbackData.PANEL_UNLOCK_PREFIX}{chat_id}"
        keyboard.append([
            InlineKeyboardButton(lock_label, callback_data=lock_callback),
            InlineKeyboardButton("🗑️ حذف", callback_data=f"delete_group:{chat_id}")
        ])
        keyboard.append([InlineKeyboardButton("─" * 20, callback_data="noop")])

    keyboard.append([
        InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS),
        InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)
    ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "👥 **مجموعاتي**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر مجموعة للتحكم بها:\n\n✅ = نشطة  |  ⛔ = محظورة"
    if query:
        await safe_edit_markdown(query, text, reply_markup=reply_markup)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=reply_markup)

async def delete_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('delete_group_id')
    if not chat_id:
        return
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer("❌ غير مصرح", show_alert=True)
        else:
            await update.message.reply_text("❌ غير مصرح")
        return
    async def _delete_group(conn):
        await conn.execute("DELETE FROM bot_groups WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM user_groups_link WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM group_security WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM chat_locks WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM moderation_log WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM group_admins WHERE chat_id = ?", (chat_id,))
        await conn.commit()
    await execute_db(_delete_group)
    if query:
        await query.edit_message_text("✅ تم حذف المجموعة من قاعدة البيانات.")
    else:
        await update.message.reply_text("✅ تم حذف المجموعة من قاعدة البيانات.")
    await my_groups_callback(update, context)

# ===================================================================
# ===================== إصلاح group_settings_callback =====================
# ===================================================================
async def group_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except Exception:
            pass

    uid = update.effective_user.id
    chat_id = None

    try:
        if query and query.data:
            try:
                chat_id = int(query.data.split(":")[-1])
            except (ValueError, IndexError) as e:
                error_id = advanced_logger.log_error("فشل استخراج chat_id من الكولباك", e, {"data": query.data})
                await query.edit_message_text(f"❌ بيانات الكولباك غير صالحة (الرمز: `{error_id}`)")
                return
        else:
            chat_id = context.user_data.get('group_chat_id')

        if not chat_id:
            if query:
                await query.edit_message_text("❌ لم يتم تحديد المجموعة")
            else:
                await context.bot.send_message(chat_id=uid, text="❌ لم يتم تحديد المجموعة")
            return

        try:
            is_auth = await is_authorized_in_group(context.bot, chat_id, uid)
        except Exception as e:
            error_id = advanced_logger.log_error("فشل التحقق من الصلاحية", e, {"chat_id": chat_id, "user_id": uid})
            if query:
                await query.edit_message_text(f"❌ فشل التحقق من الصلاحية (الرمز: `{error_id}`)")
            else:
                await context.bot.send_message(chat_id=uid, text=f"❌ فشل التحقق من الصلاحية (الرمز: `{error_id}`)")
            return

        if not is_auth:
            if query:
                await query.edit_message_text(get_text(uid, 'admin_only'))
            else:
                await context.bot.send_message(chat_id=uid, text=get_text(uid, 'admin_only'))
            return

        try:
            settings = await db_get_security_settings(chat_id)
        except Exception as e:
            error_id = advanced_logger.log_error("فشل جلب إعدادات الأمان", e, {"chat_id": chat_id})
            if query:
                await query.edit_message_text(f"❌ فشل جلب إعدادات الأمان (الرمز: `{error_id}`)")
            else:
                await context.bot.send_message(chat_id=uid, text=f"❌ فشل جلب إعدادات الأمان (الرمز: `{error_id}`)")
            return

        async def _get_group_name(conn):
            cur = await conn.execute("SELECT chat_name FROM bot_groups WHERE chat_id=?", (chat_id,))
            row = await cur.fetchone()
            if row and row[0]:
                name = row[0]
                if len(name) > 50:
                    name = name[:47] + "..."
                return name
            return str(chat_id)

        try:
            gname = await execute_db(_get_group_name)
        except Exception as e:
            error_id = advanced_logger.log_error("فشل جلب اسم المجموعة", e, {"chat_id": chat_id})
            gname = str(chat_id)
            logger.warning(f"استخدمنا المعرف كاسم بديل للخطأ {error_id}")

        text = f"⚙️ **لوحة تحكم المجموعة: {gname}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        text += f"🔗 حذف الروابط: {'✅' if settings.get('links', False) else '❌'}\n"
        text += f"@ حذف المعرفات: {'✅' if settings.get('mentions', False) else '❌'}\n"
        text += f"🚫 كلمات محظورة: {'✅' if settings.get('delete_banned_words', False) else '❌'}\n"
        text += f"⏱️ وضع بطيء: {'✅' if settings.get('slow_mode', False) else '❌'}\n"
        text += f"🎯 رسالة ترحيب: {'✅' if settings.get('welcome_enabled', False) else '❌'}\n"
        text += f"👋 رسالة وداع: {'✅' if settings.get('goodbye_enabled', False) else '❌'}\n"
        text += f"🔊 رسالة تحذير: {'✅' if settings.get('warn', True) else '❌'}\n"
        text += f"🎬 حذف الفيديوهات: {'✅' if settings.get('delete_videos', False) else '❌'}\n"
        text += f"🛠️ حذف رسائل الخدمة: {'✅' if settings.get('delete_service', False) else '❌'}\n"
        text += f"📄 حذف الملفات: {'✅' if settings.get('delete_documents', False) else '❌'}\n"
        text += f"🖼️ حذف الملصقات: {'✅' if settings.get('delete_stickers', False) else '❌'}\n"
        text += f"━━━━━━━━━━━━━━━━━━━━━━\n"
        penalty = settings.get('auto_penalty', 'none')
        if penalty == 'kick':
            penalty_text = "طرد"
        elif penalty == 'ban':
            penalty_text = "حظر"
        elif penalty == 'mute':
            penalty_text = "كتم"
        else:
            penalty_text = "لا شيء"
        text += f"⚖️ **العقوبة التلقائية:** {penalty_text}\n"
        if penalty == 'mute':
            minutes = settings.get('auto_mute_duration', 60)
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

        if query:
            await safe_edit_markdown(query, text, reply_markup=security_keyboard(chat_id))
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=security_keyboard(chat_id))

    except Exception as e:
        error_id = advanced_logger.log_error(
            "خطأ غير متوقع في group_settings_callback",
            e,
            {"chat_id": chat_id, "user_id": uid}
        )
        try:
            if query:
                await query.edit_message_text(
                    f"❌ حدث خطأ:\n`{str(e)[:300]}`\n(الرمز: `{error_id}`)"
                )
            else:
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"❌ حدث خطأ:\n`{str(e)[:300]}`\n(الرمز: `{error_id}`)"
                )
        except Exception as e2:
            logger.error(f"فشل إرسال رسالة الخطأ للمستخدم: {e2}")

# ===================================================================

async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    auto = await db_auto_status(uid)
    auto_btn = get_text(uid, 'disabled') if auto else get_text(uid, 'enabled')
    recycle = await db_get_auto_recycle(uid)
    recycle_btn = get_text(uid, 'enabled') if recycle else get_text(uid, 'disabled')
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{auto_btn} النشر التلقائي", callback_data=CallbackData.SETTINGS_TOGGLE_AUTO_PUBLISH)],
        [InlineKeyboardButton(f"♻️ إعادة التدوير: {recycle_btn}", callback_data=CallbackData.SETTINGS_TOGGLE_AUTO_RECYCLE)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    if query:
        await query.edit_message_text(get_text(uid, 'settings'), reply_markup=kb)
    else:
        await update.message.reply_text(get_text(uid, 'settings'), reply_markup=kb)

async def toggle_auto_publish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    cur = await db_auto_status(uid)
    await db_set_auto(uid, not cur)
    status = get_text(uid, 'enabled') if not cur else get_text(uid, 'disabled')
    if query:
        await query.edit_message_text(get_text(uid, 'auto_toggled').format(status))
    else:
        await update.message.reply_text(get_text(uid, 'auto_toggled').format(status))
    await main_menu_callback(update, context)

async def toggle_auto_recycle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    cur = await db_get_auto_recycle(uid)
    new_status = not cur
    await db_set_auto_recycle(uid, new_status)
    status = get_text(uid, 'enabled') if new_status else get_text(uid, 'disabled')
    if query:
        await query.edit_message_text(f"✅ تم تغيير إعادة التدوير التلقائي إلى: {status}")
    else:
        await update.message.reply_text(f"✅ تم تغيير إعادة التدوير التلقائي إلى: {status}")
    await settings_menu_callback(update, context)

# ===================== معالجات الكولباك للجدولة =====================
async def schedule_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    parts = query.data.split(":") if query else context.user_data.get('schedule_data', '').split(":")
    if len(parts) >= 3:
        ch_db_id = int(parts[-1])
    else:
        ch_db_id = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if not ch_db_id:
        if query:
            await query.edit_message_text("⚠️ يرجى اختيار قناة أولاً")
        else:
            await update.message.reply_text("⚠️ يرجى اختيار قناة أولاً")
        return
    schedule = await db_get_schedule(ch_db_id)
    if schedule['type'] == 'interval_minutes':
        txt = get_text(uid, 'interval_minutes').format(schedule['interval_minutes'])
    elif schedule['type'] == 'interval_hours':
        txt = get_text(uid, 'interval_hours').format(schedule['interval_hours'])
    elif schedule['type'] == 'interval_days':
        txt = get_text(uid, 'interval_days').format(schedule['interval_days'])
    elif schedule['type'] == 'days':
        days = parse_days_of_week_safe(schedule['days_of_week'])
        day_names = [get_text(uid, 'monday'), get_text(uid, 'tuesday'), get_text(uid, 'wednesday'),
                     get_text(uid, 'thursday'), get_text(uid, 'friday'), get_text(uid, 'saturday'),
                     get_text(uid, 'sunday')]
        txt = get_text(uid, 'days_week').format(', '.join([day_names[d] for d in days]) if days else get_text(uid, 'nothing'))
    elif schedule['type'] == 'cron':
        txt = f"⏰ CRON: {schedule.get('cron_expression', 'غير محدد')}"
    else:
        dates = parse_dates_safe(schedule['specific_dates'])
        txt = get_text(uid, 'specific_dates').format(', '.join(dates) if dates else get_text(uid, 'nothing'))
    pub_time = schedule.get('publish_time', '00:00')
    txt += f"\n🕐 وقت النشر: {pub_time} (بتوقيت مكة)"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 دقائق", callback_data=f"{CallbackData.SCHEDULE_SET_INTERVAL_MINUTES_PREFIX}{ch_db_id}"),
         InlineKeyboardButton("🕒 ساعات", callback_data=f"{CallbackData.SCHEDULE_SET_INTERVAL_HOURS_PREFIX}{ch_db_id}")],
        [InlineKeyboardButton("📆 أيام", callback_data=f"{CallbackData.SCHEDULE_SET_INTERVAL_DAYS_PREFIX}{ch_db_id}"),
         InlineKeyboardButton("📅 أيام أسبوع", callback_data=f"{CallbackData.SCHEDULE_SET_DAYS_PREFIX}{ch_db_id}")],
        [InlineKeyboardButton("🗓️ تواريخ محددة", callback_data=f"{CallbackData.SCHEDULE_SET_DATES_PREFIX}{ch_db_id}"),
         InlineKeyboardButton("⏰ وقت النشر", callback_data=f"{CallbackData.SCHEDULE_SET_PUBLISH_TIME_PREFIX}{ch_db_id}")],
        [InlineKeyboardButton("⏱️ CRON", callback_data=f"schedule:set_cron:{ch_db_id}")],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, get_text(uid, 'schedule_settings').format(txt), reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, get_text(uid, 'schedule_settings').format(txt), reply_markup=kb)

async def set_interval_minutes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('schedule_ch_id')
    if not ch_db_id:
        return
    context.user_data['state'] = UserState.WAITING_INTERVAL_MINUTES
    context.user_data['schedule_ch_id'] = ch_db_id
    if query:
        await query.edit_message_text(get_text(uid, 'send_minutes'))
    else:
        await update.message.reply_text(get_text(uid, 'send_minutes'))

async def set_interval_hours_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('schedule_ch_id')
    if not ch_db_id:
        return
    context.user_data['state'] = UserState.WAITING_INTERVAL_HOURS
    context.user_data['schedule_ch_id'] = ch_db_id
    if query:
        await query.edit_message_text(get_text(uid, 'send_hours'))
    else:
        await update.message.reply_text(get_text(uid, 'send_hours'))

async def set_interval_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('schedule_ch_id')
    if not ch_db_id:
        return
    context.user_data['state'] = UserState.WAITING_INTERVAL_DAYS
    context.user_data['schedule_ch_id'] = ch_db_id
    if query:
        await query.edit_message_text(get_text(uid, 'send_days'))
    else:
        await update.message.reply_text(get_text(uid, 'send_days'))

async def set_cron_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('schedule_ch_id')
    if not ch_db_id:
        return
    context.user_data['state'] = UserState.WAITING_INTERVAL_MINUTES
    context.user_data['schedule_ch_id'] = ch_db_id
    context.user_data['schedule_cron'] = True
    msg = "⏱️ **إعداد CRON**\n\nأرسل تعبير CRON (مثال: `0 12 * * *` للنشر يومياً الساعة 12:00)\n\nالشرح:\n• دقيقة (0-59)\n• ساعة (0-23)\n• يوم (1-31)\n• شهر (1-12)\n• يوم أسبوع (0-6)"
    if query:
        await query.edit_message_text(msg, parse_mode="MarkdownV2")
    else:
        await update.message.reply_text(msg, parse_mode="MarkdownV2")

async def set_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('schedule_ch_id')
    if not ch_db_id:
        return
    context.user_data['selected_days_ch'] = ch_db_id
    context.user_data['selected_days'] = []
    context.user_data['state'] = UserState.SELECTING_DAYS
    if query:
        await query.edit_message_text("اختر أيام النشر (بتوقيت مكة):", reply_markup=await build_days_keyboard(uid, context))
    else:
        await update.message.reply_text("اختر أيام النشر (بتوقيت مكة):", reply_markup=await build_days_keyboard(uid, context))

async def set_dates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('schedule_ch_id')
    if not ch_db_id:
        return
    context.user_data['state'] = UserState.WAITING_DATES
    context.user_data['schedule_ch_id'] = ch_db_id
    if query:
        await query.edit_message_text(get_text(uid, 'send_dates'))
    else:
        await update.message.reply_text(get_text(uid, 'send_dates'))

async def set_publish_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('schedule_ch_id')
    if not ch_db_id:
        return
    context.user_data['state'] = UserState.WAITING_PUBLISH_TIME
    context.user_data['schedule_ch_id'] = ch_db_id
    if query:
        await query.edit_message_text(get_text(uid, 'send_time'))
    else:
        await update.message.reply_text(get_text(uid, 'send_time'))

async def day_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    day = int(query.data.split(":")[-1]) if query else context.user_data.get('selected_day')
    if day is None:
        return
    selected = context.user_data.get('selected_days', [])
    if day in selected:
        selected.remove(day)
    else:
        selected.append(day)
    context.user_data['selected_days'] = selected
    if query:
        await query.edit_message_text("اختر أيام النشر (بتوقيت مكة):", reply_markup=await build_days_keyboard(uid, context))
    else:
        await update.message.reply_text("اختر أيام النشر (بتوقيت مكة):", reply_markup=await build_days_keyboard(uid, context))

async def save_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch = context.user_data.get('selected_days_ch')
    if ch:
        days_json = json.dumps(context.user_data.get('selected_days', []))
        await db_save_schedule(ch, 'days', days_of_week=days_json)
        await db_set_next_publish_date(ch, None)
        context.user_data.pop('selected_days_ch', None)
        context.user_data.pop('selected_days', None)
        context.user_data.pop('state', None)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]])
        if query:
            await safe_edit_markdown(query, get_text(uid, 'days_saved'), reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, get_text(uid, 'days_saved'), reply_markup=kb)
    else:
        if query:
            await query.edit_message_text(get_text(uid, 'error'))
        else:
            await update.message.reply_text(get_text(uid, 'error'))

# ===================== معالجات الكولباك للأمان =====================
async def security_links_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    settings = await db_get_security_settings(chat_id)
    settings['links'] = not settings['links']
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, 'updated'))
    else:
        await update.message.reply_text(get_text(uid, 'updated'))
    await group_settings_callback(update, context)

async def security_mentions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    settings = await db_get_security_settings(chat_id)
    settings['mentions'] = not settings['mentions']
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, 'updated'))
    else:
        await update.message.reply_text(get_text(uid, 'updated'))
    await group_settings_callback(update, context)

async def security_warn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    settings = await db_get_security_settings(chat_id)
    settings['warn'] = not settings['warn']
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, 'updated'))
    else:
        await update.message.reply_text(get_text(uid, 'updated'))
    await group_settings_callback(update, context)

async def security_slowmode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    settings = await db_get_security_settings(chat_id)
    settings['slow_mode'] = not settings['slow_mode']
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, 'updated'))
    else:
        await update.message.reply_text(get_text(uid, 'updated'))
    await group_settings_callback(update, context)

async def security_banned_words_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['banned_words_chat_id'] = chat_id
    msg = "🚫 إدارة الكلمات المحظورة للمجموعة"
    if query:
        await query.edit_message_text(msg, reply_markup=get_group_banned_words_keyboard(chat_id))
    else:
        await update.message.reply_text(msg, reply_markup=get_group_banned_words_keyboard(chat_id))

# ===================== معالجات الكولباك الجديدة لحذف الفيديوهات ورسائل الخدمة والملفات والملصقات =====================

async def security_delete_videos_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    settings = await db_get_security_settings(chat_id)
    settings['delete_videos'] = not settings.get('delete_videos', False)
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, 'updated'))
    else:
        await update.message.reply_text(get_text(uid, 'updated'))
    await group_settings_callback(update, context)

async def security_delete_service_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    settings = await db_get_security_settings(chat_id)
    settings['delete_service'] = not settings.get('delete_service', False)
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, 'updated'))
    else:
        await update.message.reply_text(get_text(uid, 'updated'))
    await group_settings_callback(update, context)

async def security_delete_documents_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    settings = await db_get_security_settings(chat_id)
    settings['delete_documents'] = not settings.get('delete_documents', False)
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, 'updated'))
    else:
        await update.message.reply_text(get_text(uid, 'updated'))
    await group_settings_callback(update, context)

async def security_delete_stickers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    settings = await db_get_security_settings(chat_id)
    settings['delete_stickers'] = not settings.get('delete_stickers', False)
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, 'updated'))
    else:
        await update.message.reply_text(get_text(uid, 'updated'))
    await group_settings_callback(update, context)

async def security_welcome_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    settings = await db_get_security_settings(chat_id)
    settings['welcome_enabled'] = not settings['welcome_enabled']
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, 'updated'))
    else:
        await update.message.reply_text(get_text(uid, 'updated'))
    await group_settings_callback(update, context)

async def security_goodbye_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    settings = await db_get_security_settings(chat_id)
    settings['goodbye_enabled'] = not settings['goodbye_enabled']
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, 'updated'))
    else:
        await update.message.reply_text(get_text(uid, 'updated'))
    await group_settings_callback(update, context)

async def security_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.message.delete()

async def security_main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    context.user_data['state'] = UserState.WAITING_GROUP_SECURITY
    msg = get_text(uid, 'security_main')
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def security_select_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        error_text = """❌ **غير مصرح**

أنت لست مشرفاً في هذه المجموعة، أو البوت ليس مشرفاً.

تأكد من:
1. أن البوت مشرف في المجموعة
2. أن لديك صلاحيات مشرف في المجموعة"""
        if query:
            await safe_edit_markdown(query, error_text)
        else:
            await update.message.reply_text(error_text)
        return
    settings = await db_get_security_settings(chat_id)
    async def _get_group_name(conn):
        cur = await conn.execute("SELECT chat_name FROM bot_groups WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        name = row[0] if row else str(chat_id)
        if len(name) > 50:
            name = name[:47] + "..."
        return name
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
🎬 حذف الفيديوهات: {'✅' if settings.get('delete_videos', False) else '❌'}
🛠️ حذف رسائل الخدمة: {'✅' if settings.get('delete_service', False) else '❌'}
📄 حذف الملفات: {'✅' if settings.get('delete_documents', False) else '❌'}
🖼️ حذف الملصقات: {'✅' if settings.get('delete_stickers', False) else '❌'}
━━━━━━━━━━━━━━━━━━━━━━
⚖️ **العقوبة التلقائية:** {'طرد' if settings.get('auto_penalty') == 'kick' else 'حظر' if settings.get('auto_penalty') == 'ban' else 'كتم' if settings.get('auto_penalty') == 'mute' else 'لا شيء'}
━━━━━━━━━━━━━━━━━━━━━━
💡 **اختر الإجراء المناسب:**"""
    if query:
        await safe_edit_markdown(query, text, reply_markup=security_keyboard(chat_id))
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=security_keyboard(chat_id))

async def security_refresh_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    groups = await db_get_user_groups(uid)
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
3. استخدم الأمر /syncgroup في المجموعة
4. ثم عد إلى الخاص واضغط على تحديث
5. إذا كنت مالكاً مخفياً، استخدم الأمر /register_hidden_owner في المجموعة"""
        if query:
            await safe_edit_markdown(query, text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)
        return
    keyboard = []
    for group in groups:
        chat_id, chat_name, username, banned = group
        name = chat_name[:40] + "..." if len(chat_name) > 43 else chat_name
        keyboard.append([InlineKeyboardButton(f"📌 {name}", callback_data=f"{CallbackData.SECURITY_SELECT_GROUP}{chat_id}")])
    keyboard.append([InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS)])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    text = """🔐 **إعدادات الأمان والإجراءات المتقدمة**

📌 اختر المجموعة التي تريد إدارة إعداداتها:

⚠️ ملاحظة: يجب أن يكون البوت مشرفاً في المجموعة
🔒 للمالك المخفي: استخدم /register_hidden_owner في المجموعة أولاً"""
    if query:
        await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=InlineKeyboardMarkup(keyboard))

# ===================== معالجات الكولباك للكلمات المحظورة =====================
async def banned_words_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('banned_words_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_GROUP_BANNED_WORD
    context.user_data['banned_words_chat_id'] = chat_id
    msg = "➕ أرسل الكلمة التي تريد إضافتها للكلمات المحظورة:"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def banned_words_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('banned_words_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    words = await db_get_banned_words(chat_id)
    if not words:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}")]])
        if query:
            await query.edit_message_text("📭 لا توجد كلمات محظورة في هذه المجموعة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد كلمات محظورة في هذه المجموعة.", reply_markup=kb)
        return
    text = "🚫 **الكلمات المحظورة في المجموعة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for word, added_by, added_at in words[:20]:
        text += f"• `{word}` (أضيف بواسطة {added_by})\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}")]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def banned_words_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('banned_words_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_REMOVE_GROUP_BANNED_WORD
    context.user_data['banned_words_chat_id'] = chat_id
    msg = "🗑️ أرسل الكلمة التي تريد حذفها من الكلمات المحظورة:"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

# ===================== معالجات الكولباك للعقوبات =====================
async def penalty_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    msg = "⚖️ **اختر العقوبة التلقائية:**\n\nسيتم تطبيق هذه العقوبة عند مخالفة قواعد الحماية:"
    if query:
        await query.edit_message_text(msg, reply_markup=penalty_keyboard(chat_id))
    else:
        await update.message.reply_text(msg, reply_markup=penalty_keyboard(chat_id))

async def penalty_kick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    await db_set_security_settings(chat_id, auto_penalty='kick')
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
    if query:
        await query.edit_message_text("✅ تم تعيين العقوبة التلقائية إلى: **طرد**", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم تعيين العقوبة التلقائية إلى: **طرد**", reply_markup=kb)

async def penalty_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    await db_set_security_settings(chat_id, auto_penalty='ban')
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
    if query:
        await query.edit_message_text("✅ تم تعيين العقوبة التلقائية إلى: **حظر**", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم تعيين العقوبة التلقائية إلى: **حظر**", reply_markup=kb)

async def penalty_mute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['penalty_chat_id'] = chat_id
    msg = "🔇 **اختر مدة الكتم:**"
    if query:
        await query.edit_message_text(msg, reply_markup=mute_duration_keyboard(chat_id))
    else:
        await update.message.reply_text(msg, reply_markup=mute_duration_keyboard(chat_id))

async def penalty_mute_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    data_parts = query.data.split(":") if query else context.user_data.get('penalty_mute_data', '').split(":")
    if len(data_parts) == 3:
        duration = data_parts[1]
        chat_id = int(data_parts[2])
        uid = update.effective_user.id
        if not await is_authorized_in_group(context.bot, chat_id, uid):
            if query:
                await query.answer(get_text(uid, 'admin_only'), show_alert=True)
            else:
                await update.message.reply_text(get_text(uid, 'admin_only'))
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
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
        if query:
            await query.edit_message_text(f"✅ تم تعيين العقوبة التلقائية إلى: **كتم {text}**", reply_markup=kb)
        else:
            await update.message.reply_text(f"✅ تم تعيين العقوبة التلقائية إلى: **كتم {text}**", reply_markup=kb)
# ===================== معالجات الكولباك للدعم =====================
async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, get_text(user_id, 'help'), reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, get_text(user_id, 'help'), reply_markup=keyboard)

async def support_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    context.user_data['support_mode'] = True
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 كتابة تذكرة", callback_data=CallbackData.SUPPORT_TICKET)],
        [InlineKeyboardButton("❓ المساعدة", callback_data=CallbackData.SUPPORT_HELP)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    text = get_text(user_id, 'support_welcome')
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def support_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.SUPPORT_MENU)]
    ])
    text = get_text(user_id, 'support_help')
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def support_ticket_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    context.user_data['support_mode'] = True
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 إلغاء", callback_data=CallbackData.SUPPORT_MENU)]
    ])
    text = "📝 **اكتب رسالتك** (سيتم إرسالها كتذكرة دعم)\nيمكنك إلغاء العملية بالضغط على الزر أدناه."
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def support_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await support_menu_callback(update, context)

# ===================== معالجات الكولباك للتجربة والاشتراك =====================
async def trial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if await db_has_used_trial(uid):
        if query:
            await query.edit_message_text(get_text(uid, 'trial_used'))
        else:
            await update.message.reply_text(get_text(uid, 'trial_used'))
        return
    if await db_has_active_subscription(uid):
        if query:
            await query.edit_message_text(get_text(uid, 'already_subscribed'))
        else:
            await update.message.reply_text(get_text(uid, 'already_subscribed'))
        return
    await db_activate_trial(uid)
    if query:
        await query.edit_message_text(get_text(uid, 'trial'))
    else:
        await update.message.reply_text(get_text(uid, 'trial'))
    await main_menu_callback(update, context)

async def subscribe_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if await db_has_active_subscription(uid):
        days = await db_get_subscription_days_left(uid)
        msg = f"✅ اشتراكك مفعل، متبقي {days} يوم\nشكراً لدعمك ❤️"
        if query:
            await query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ 1 يوم - 5 نجوم", callback_data=CallbackData.BUY_SUBSCRIPTION_1),
         InlineKeyboardButton("⭐ 2 يوم - 9 نجوم", callback_data=CallbackData.BUY_SUBSCRIPTION_2)],
        [InlineKeyboardButton("⭐ شهر (30 يوم) - 50 نجمة", callback_data=CallbackData.BUY_SUBSCRIPTION_30),
         InlineKeyboardButton("⭐ 3 أشهر (90 يوم) - 120 نجمة", callback_data=CallbackData.BUY_SUBSCRIPTION_90)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    text = get_text(uid, 'subscribe')
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)

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
        if "Stars" in str(e):
            if query:
                await query.edit_message_text("❌ الدفع بالنجوم غير مفعل حالياً، استخدم /trial")
            else:
                await update.message.reply_text("❌ الدفع بالنجوم غير مفعل حالياً، استخدم /trial")
        else:
            if query:
                await query.edit_message_text(f"❌ خطأ: {str(e)[:100]}")
            else:
                await update.message.reply_text(f"❌ خطأ: {str(e)[:100]}")

async def buy_subscription_1_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    await buy_subscription_callback(update, context, 1, 5, "اشتراك 1 يوم")

async def buy_subscription_2_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    await buy_subscription_callback(update, context, 2, 9, "اشتراك 2 يوم")

async def buy_subscription_30_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    await buy_subscription_callback(update, context, 30, 50, "اشتراك شهر")

async def buy_subscription_90_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    await buy_subscription_callback(update, context, 90, 120, "اشتراك 3 أشهر")

# ===================== معالجات الكولباك للمطور والتحديثات =====================
async def developer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    metrics_stats = metrics.get_stats()
    text = f"""👑 **معلومات المطور**
━━━━━━━━━━━━━━━━━━━━━━
🤖 **البوت:** {BOT_NAME}
📦 **الإصدار:** 19.3.3
👨‍💻 **المطور:** @RelaxMgr

🔐 **الميزات الأمنية المتقدمة:**
• تشفير قاعدة البيانات بكلمة مرور (PBKDF2)
• نظام كشف النشاط المشبوه
• تخزين مؤقت محسن مع دعم Redis
• Pool اتصالات قاعدة البيانات
• إعادة تدوير المنشورات تلقائياً (مع زر تحكم)
• إحصائيات متقدمة للقنوات
• رسم بياني لنمو القناة
• نظام Rate Limiting متقدم
• مصادقة ثنائية (2FA)
• دعم جميع أنواع الميديا
• مترجم ذكي غير متزامن
• WebSocket للتحديثات الفورية
• نسخ احتياطي تدريجي وضغط محسن
• Health Check متقدم
• مراقبة الذاكرة التلقائية
• نظام المسابقات المتكامل
• واجهة ويب متكاملة
• حماية واجهة الويب بكلمة مرور
• مفتاح تشفير منفصل للنسخ الاحتياطي
• تنقية النصوص باستخدام bleach
• إدارة المهام بـ Semaphore
• 200 رد تلقائي للمجموعات مع أوزان
• نظام ردود ذكي مع تحليل المشاعر
• دعم المالك والمشرفين المخفيين المتعددين
• نظام ردود متقدم مع إعدادات لكل مجموعة
• إمكانية تفعيل/تعطيل الردود لكل مجموعة
• وضع المشرفين فقط للردود
• تشفير بيانات الكولباك
• حد أقصى للمنشورات غير المنشورة
• 🔞 كشف المحتوى غير اللائق (NSFW) مع تخزين مؤقت
• 📥 استيراد الكلمات المحظورة من ملف مع دعم Regex
• 🌐 دعم 12 لغة مع ترجمة تلقائية
• 📊 رسوم بيانية تفاعلية في واجهة الويب
• 📤 تصدير البيانات (CSV)
• 🌙 وضع Dark Mode
• ⏱️ جدولة CRON
• 👑 دعم كامل للمشرفين المتعددين (جميع المشرفين الحقيقيين يظهرون في مجموعاتهم)
• 🎬 حذف الفيديوهات التلقائي
• 🛠️ حذف رسائل الخدمة التلقائي
• 📄 حذف الملفات التلقائي
• 🖼️ حذف الملصقات التلقائي

⚡ **وضع السرعة:** {'مفعل' if not BATTERY_SAVER_MODE else 'معطل'}

📊 **إحصائيات الأداء:**
• وقت التشغيل: {int(metrics_stats['uptime'] / 3600)} ساعة
• إجمالي الأوامر: {metrics_stats['total_commands']}
• متوسط وقت الاستجابة: {metrics_stats['avg_response_time']:.2f} ثانية

━━━━━━━━━━━━━━━━━━━━━━
📞 **طرق التواصل:**
✅ **تيليجرام:** @RelaxMgr
✅ **البوت:** @{BOT_USERNAME}"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 تواصل مع المطور", url=f"https://t.me/RelaxMgr")],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def updates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    updates_channel = await db_get_updates_channel()
    if updates_channel:
        text = f"""📢 **قناة التحديثات**
━━━━━━━━━━━━━━━━━━━━━━
📌 القناة: @{updates_channel}

📢 تابع القناة لمعرفة آخر التحديثات:
• ميزات جديدة ✨
• تحسينات الأداء ⚡
• إصلاحات الأخطاء 🔧
• عروض حصرية 🎁

🔗 اضغط على الزر أدناه لفتح القناة."""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 افتح القناة", url=f"https://t.me/{updates_channel}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
    else:
        text = """📢 **لم يتم تعيين قناة التحديثات بعد**

📌 **لتعيين قناة التحديثات:**
1. استخدم `/admin_panel`
2. اضغط على `⚙️ قناة التحديثات`
3. أرسل معرف القناة

⚠️ تأكد من أن البوت مشرف في القناة."""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👑 الذهاب للوحة الأدمن", callback_data=CallbackData.ADMIN_PANEL)],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

# ===================== معالجات الكولباك للإحالات =====================
async def referral_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    referral_code = await db_get_referral_code(uid)
    if not referral_code:
        referral_code = await db_generate_referral_code(uid)
    stats = await db_get_referral_stats(uid)
    settings = await db_get_referral_settings()
    reward_days = int(settings.get('reward_days_per_referral', '3'))
    welcome_points = int(settings.get('welcome_bonus_points', '10'))
    text = get_text(uid, 'referral_title').format(referral_code, BOT_USERNAME, referral_code, stats['total_referrals'], stats['available_days'], reward_days, welcome_points)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(uid, 'copy_link'), callback_data=f"{CallbackData.REFERRAL_COPY_LINK_PREFIX}{referral_code}"),
         InlineKeyboardButton(get_text(uid, 'claim_reward'), callback_data=CallbackData.REFERRAL_CLAIM_REWARD)],
        [InlineKeyboardButton(get_text(uid, 'referral_list'), callback_data=CallbackData.REFERRAL_LIST),
         InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def referral_copy_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    referral_code = query.data.split(":")[-1] if query else context.user_data.get('referral_code')
    if not referral_code:
        return
    text = f"🔗 **رابط الإحالة الخاص بك:**\n`https://t.me/{BOT_USERNAME}?start=ref_{referral_code}`\n\nيمكنك الضغط مع الاستمرار على الرابط لنسخه."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REFERRAL_MENU)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def referral_claim_reward_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    stats = await db_get_referral_stats(uid)
    if stats['available_days'] <= 0:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REFERRAL_MENU)]])
        if query:
            await safe_edit_markdown(query, get_text(uid, 'no_reward_available'), reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, get_text(uid, 'no_reward_available'), reply_markup=kb)
        return
    claimed = await db_claim_referral_reward(uid)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REFERRAL_MENU)]])
    if query:
        await safe_edit_markdown(query, get_text(uid, 'reward_claimed').format(claimed), reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, get_text(uid, 'reward_claimed').format(claimed), reply_markup=kb)

async def referral_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    async def _get_referrals(conn):
        cur = await conn.execute("SELECT r.referred_id, r.referred_at, r.is_rewarded, u.first_name, u.username FROM referrals r LEFT JOIN users_cache u ON r.referred_id = u.user_id WHERE r.referrer_id = ? ORDER BY r.referred_at DESC LIMIT 20", (uid,))
        return await cur.fetchall()
    referrals = await execute_db(_get_referrals)
    if not referrals:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REFERRAL_MENU)]])
        if query:
            await safe_edit_markdown(query, get_text(uid, 'no_referrals'), reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, get_text(uid, 'no_referrals'), reply_markup=kb)
        return
    text = f"📊 **{get_text(uid, 'referral_list')}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
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
        [InlineKeyboardButton(get_text(uid, 'claim_reward'), callback_data=CallbackData.REFERRAL_CLAIM_REWARD)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REFERRAL_MENU)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

# ===================== معالجات الكولباك للتذكيرات =====================
async def reminder_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    settings = await db_get_user_reminder_settings(uid)
    status_sub = "🟢 مفعل" if settings['subscription_reminder'] else "🔴 معطل"
    status_daily = "🟢 مفعل" if settings['daily_stats_reminder'] else "🔴 معطل"
    status_weekly = "🟢 مفعل" if settings['weekly_report'] else "🔴 معطل"
    text = get_text(uid, 'reminder_title').format(status_sub, status_daily, status_weekly, settings['reminder_days_before'])
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(uid, 'reminder_sub'), callback_data=CallbackData.REMINDER_TOGGLE_SUB),
         InlineKeyboardButton(get_text(uid, 'reminder_daily'), callback_data=CallbackData.REMINDER_TOGGLE_DAILY)],
        [InlineKeyboardButton(get_text(uid, 'reminder_weekly'), callback_data=CallbackData.REMINDER_TOGGLE_WEEKLY),
         InlineKeyboardButton(get_text(uid, 'reminder_days_btn'), callback_data=CallbackData.REMINDER_SET_DAYS)],
        [InlineKeyboardButton(get_text(uid, 'reminder_lang_btn'), callback_data=CallbackData.REMINDER_SET_LANG),
         InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def reminder_toggle_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    settings = await db_get_user_reminder_settings(uid)
    await db_update_reminder_settings(uid, subscription_reminder=not settings['subscription_reminder'])
    await reminder_menu_callback(update, context)

async def reminder_toggle_daily_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    settings = await db_get_user_reminder_settings(uid)
    await db_update_reminder_settings(uid, daily_stats_reminder=not settings['daily_stats_reminder'])
    await reminder_menu_callback(update, context)

async def reminder_toggle_weekly_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    settings = await db_get_user_reminder_settings(uid)
    await db_update_reminder_settings(uid, weekly_report=not settings['weekly_report'])
    await reminder_menu_callback(update, context)

async def reminder_set_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    context.user_data['state'] = UserState.WAITING_REMINDER_DAYS
    msg = "⏰ **عدد أيام التذكير**\n\nأرسل عدد الأيام التي تريد أن يتم تذكيرك بها قبل انتهاء الاشتراك (1-10 أيام):"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REMINDER_MENU)]])
    if query:
        await query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

async def reminder_set_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("العربية 🇸🇦", callback_data=f"{CallbackData.REMINDER_LANG_PREFIX}ar"),
         InlineKeyboardButton("English 🇬🇧", callback_data=f"{CallbackData.REMINDER_LANG_PREFIX}en")],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REMINDER_MENU)]
    ])
    msg = "🌐 **اختر لغة الإشعارات:**"
    if query:
        await query.edit_message_text(msg, reply_markup=keyboard)
    else:
        await update.message.reply_text(msg, reply_markup=keyboard)

async def reminder_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    lang = query.data.split(":")[-1] if query else context.user_data.get('reminder_lang')
    if not lang:
        return
    await db_update_reminder_settings(uid, notification_lang=lang)
    await reminder_menu_callback(update, context)

# ===================== معالجات الكولباك للترجمة =====================
async def translation_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    current_lang = await get_user_translation_language(uid)
    if current_lang == 'off':
        status_text = get_text(uid, 'translation_status_off')
    elif current_lang == 'ar':
        status_text = get_text(uid, 'translation_status_on').format("العربية")
    elif current_lang == 'en':
        status_text = get_text(uid, 'translation_status_on').format("English")
    elif current_lang == 'fr':
        status_text = get_text(uid, 'translation_status_on').format("Français")
    elif current_lang == 'tr':
        status_text = get_text(uid, 'translation_status_on').format("Türkçe")
    elif current_lang == 'zh':
        status_text = get_text(uid, 'translation_status_on').format("中文")
    elif current_lang == 'ru':
        status_text = get_text(uid, 'translation_status_on').format("Русский")
    elif current_lang == 'de':
        status_text = get_text(uid, 'translation_status_on').format("Deutsch")
    elif current_lang == 'es':
        status_text = get_text(uid, 'translation_status_on').format("Español")
    elif current_lang == 'it':
        status_text = get_text(uid, 'translation_status_on').format("Italiano")
    elif current_lang == 'pt':
        status_text = get_text(uid, 'translation_status_on').format("Português")
    elif current_lang == 'ja':
        status_text = get_text(uid, 'translation_status_on').format("日本語")
    elif current_lang == 'ko':
        status_text = get_text(uid, 'translation_status_on').format("한국어")
    else:
        status_text = get_text(uid, 'translation_status_off')
    text = f"""🌐 **{get_text(uid, 'translation_settings')}**
━━━━━━━━━━━━━━━━━━━━━━
📌 **الحالة:** {status_text}
{get_text(uid, 'translation_how_it_works')}
━━━━━━━━━━━━━━━━━━━━━━
{get_text(uid, 'translation_choose')}"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(uid, 'translation_off'), callback_data=CallbackData.TRANSLATION_OFF)],
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
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def translation_off_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    await set_user_translation_language(uid, 'off')
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]])
    if query:
        await query.edit_message_text(get_text(uid, 'translation_disabled'), reply_markup=kb)
    else:
        await update.message.reply_text(get_text(uid, 'translation_disabled'), reply_markup=kb)

async def translation_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    lang = query.data.split(":")[-1] if query else context.user_data.get('translation_lang')
    if not lang:
        return
    await set_user_translation_language(uid, lang)
    lang_names = {
        'ar': 'العربية', 'en': 'English', 'fr': 'Français', 'tr': 'Türkçe',
        'zh': '中文', 'ru': 'Русский', 'de': 'Deutsch', 'es': 'Español',
        'it': 'Italiano', 'pt': 'Português', 'ja': '日本語', 'ko': '한국어'
    }
    lang_name = lang_names.get(lang, lang)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]])
    if query:
        await query.edit_message_text(get_text(uid, 'translation_enabled').format(lang_name), reply_markup=kb)
    else:
        await update.message.reply_text(get_text(uid, 'translation_enabled').format(lang_name), reply_markup=kb)

# ===================== معالجات الكولباك للوحة المشرف =====================
async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    if query:
        await safe_edit_markdown(query, get_text(uid, 'admin_panel'), reply_markup=get_admin_keyboard(uid))
    else:
        await safe_send_markdown(context.bot, uid, get_text(uid, 'admin_panel'), reply_markup=get_admin_keyboard(uid))

async def admin_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    users = await db_get_all_users()
    if not users:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا يوجد مستخدمون مسجلون.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا يوجد مستخدمون مسجلون.", reply_markup=kb)
        return
    text = "👥 **قائمة المستخدمين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for user_id, banned in users[:50]:
        status = "🚫 محظور" if banned else "✅ نشط"
        text += f"• `{user_id}` - {status}\n"
    if len(users) > 50:
        text += f"\nو {len(users)-50} آخرون..."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_banned_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    users = await db_get_all_users()
    banned_users = [u for u in users if u[1] == 1]
    if not banned_users:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا يوجد مستخدمون محظورون.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا يوجد مستخدمون محظورون.", reply_markup=kb)
        return
    text = "🚫 **المستخدمون المحظورون**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for user_id, _ in banned_users[:50]:
        text += f"• `{user_id}`\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_USERS)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def admin_unban_all_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    async def _unban_all(conn):
        await conn.execute("UPDATE users SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_unban_all)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text("✅ تم إلغاء حظر جميع المستخدمين.", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم إلغاء حظر جميع المستخدمين.", reply_markup=kb)

async def admin_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    channels = await db_get_all_user_channels_no_limit()
    if not channels:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد قنوات مسجلة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد قنوات مسجلة.", reply_markup=kb)
        return
    text = "📡 **قنوات المستخدمين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    for idx, (user_id, ch_id, ch_tele, ch_name, banned) in enumerate(channels[:100], 1):
        status = "⛔ محظورة" if banned else "✅ نشطة"
        ban_status_text = "🔓 إلغاء الحظر" if banned else "⛔ حظر"
        ban_callback = f"{CallbackData.ADMIN_TOGGLE_CHANNEL_BAN_PREFIX}{ch_id}"
        text += f"{idx}. {status} `{ch_name}`\n   👤 المستخدم: `{user_id}`\n   🆔 القناة: `{ch_tele}`\n"
        keyboard.append([InlineKeyboardButton(ban_status_text, callback_data=ban_callback)])
    if len(channels) > 100:
        text += f"\nو {len(channels)-100} قناة أخرى..."
    keyboard.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)])
    if query:
        await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_banned_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    channels = await db_all_users_channels(only_banned=True, limit=500)
    if not channels:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد قنوات محظورة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد قنوات محظورة.", reply_markup=kb)
        return
    text = "⛔ **قنوات المستخدمين المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for user_id, ch_id, ch_tele, ch_name, banned in channels[:50]:
        text += f"• المستخدم: `{user_id}` | القناة: {ch_name} (`{ch_tele}`)\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ تنشيط الكل", callback_data=CallbackData.ADMIN_ACTIVATE_ALL_CHANNELS)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def admin_activate_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    async def _activate_all(conn):
        await conn.execute("UPDATE user_channels SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_activate_all)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text("✅ تم إلغاء حظر جميع قنوات المستخدمين.", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم إلغاء حظر جميع قنوات المستخدمين.", reply_markup=kb)

async def admin_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    groups = await db_get_all_groups(only_banned=False)
    if not groups:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد مجموعات مسجلة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد مجموعات مسجلة.", reply_markup=kb)
        return
    text = "👥 **المجموعات المسجلة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    for chat_id, chat_name, username, added_by, added_at, banned in groups[:50]:
        status = "⛔ محظورة" if banned else "✅ نشطة"
        ban_status_text = "🔓 إلغاء الحظر" if banned else "⛔ حظر"
        ban_callback = f"{CallbackData.ADMIN_TOGGLE_GROUP_BAN_PREFIX}{chat_id}"
        text += f"• {chat_name} (ID: `{chat_id}`)\n  أضيف بواسطة: `{added_by}`\n  الحالة: {status}\n"
        keyboard.append([InlineKeyboardButton(ban_status_text, callback_data=ban_callback)])
    if len(groups) > 50:
        text += f"\nو {len(groups)-50} أخرى..."
    keyboard.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)])
    if query:
        await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_banned_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    groups = await db_get_all_groups(only_banned=True)
    if not groups:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد مجموعات محظورة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد مجموعات محظورة.", reply_markup=kb)
        return
    text = "🚷 **المجموعات المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for chat_id, chat_name, username, added_by, added_at, banned in groups[:50]:
        text += f"• {chat_name} (ID: `{chat_id}`)\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_GROUPS)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def admin_unban_all_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    async def _unban_groups(conn):
        await conn.execute("UPDATE bot_groups SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_unban_groups)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text("✅ تم إلغاء حظر جميع المجموعات.", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم إلغاء حظر جميع المجموعات.", reply_markup=kb)

async def admin_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    channels = await db_get_all_bot_channels(only_banned=False)
    if not channels:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد قنوات أضيف إليها البوت.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد قنوات أضيف إليها البوت.", reply_markup=kb)
        return
    text = "📢 **قنوات البوت**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for channel_id, channel_name, added_by, added_at, banned in channels[:50]:
        text += f"• {channel_name} (ID: `{channel_id}`)\n  أضيف بواسطة: `{added_by}`\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_banned_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    channels = await db_get_all_bot_channels(only_banned=True)
    if not channels:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد قنوات بوت محظورة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد قنوات بوت محظورة.", reply_markup=kb)
        return
    text = "🚫 **قنوات البوت المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for channel_id, channel_name, added_by, added_at, banned in channels[:50]:
        text += f"• {channel_name} (ID: `{channel_id}`)\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_BOT_CHANNELS)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def admin_unban_all_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    async def _unban_bot_channels(conn):
        await conn.execute("UPDATE bot_channels SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_unban_bot_channels)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text("✅ تم إلغاء حظر جميع قنوات البوت.", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم إلغاء حظر جميع قنوات البوت.", reply_markup=kb)

async def admin_monitor_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
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
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_add_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_ADMIN_ID_ADD
    if query:
        await safe_edit_markdown(query, "👑 أرسل معرف المستخدم (user_id) لإضافته كمشرف:")
    else:
        await update.message.reply_text("👑 أرسل معرف المستخدم (user_id) لإضافته كمشرف:")

async def admin_remove_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    admins = await get_all_bot_admins()
    if not admins:
        if query:
            await query.edit_message_text("📭 لا يوجد مشرفون لإزالتهم.")
        else:
            await update.message.reply_text("📭 لا يوجد مشرفون لإزالتهم.")
        return
    text = "👑 **المشرفون الحاليون:**\n"
    for a in admins:
        text += f"- `{a}`\n"
    text += "\n🗑️ أرسل معرف المستخدم (user_id) لإزالته من المشرفين:"
    context.user_data['state'] = UserState.WAITING_ADMIN_ID_REMOVE
    if query:
        await safe_edit_markdown(query, text)
    else:
        await update.message.reply_text(text)

async def admin_ram_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    ram = get_ram_usage()
    text = f"🖥️ **حالة الرام**\n━━━━━━━━━━━━━━━━━━━━━━\n• الإجمالي: {ram['total']} GB\n• المستخدم: {ram['used']} GB\n• النسبة: {ram['percent']}%"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    total, banned, posts, groups, channels = await db_stats()
    text = f"📊 **إحصائيات عامة**\n━━━━━━━━━━━━━━━━━━━━━━\n• المستخدمين: {total}\n• المحظورين: {banned}\n• المنشورات غير المنشورة: {posts}\n• المجموعات: {groups}\n• قنوات المستخدمين: {channels}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_metrics_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    stats = metrics.get_stats()
    ram = get_ram_usage()
    text = f"""📈 **مقاييس الأداء**
━━━━━━━━━━━━━━━━━━━━━━
⏱️ **وقت التشغيل:** {int(stats['uptime'] / 3600)} ساعة {int((stats['uptime'] % 3600) / 60)} دقيقة
📊 **إجمالي الأوامر:** {stats['total_commands']}
⚡ **متوسط وقت الاستجابة:** {stats['avg_response_time']:.3f} ثانية
🖥️ **حالة النظام:**
• إجمالي الرام: {ram['total']} GB
• المستخدم: {ram['used']} GB
• النسبة: {ram['percent']}%
📋 **الأخطاء المسجلة:**
{chr(10).join([f'• {k}: {v}' for k, v in stats['errors'].items()]) if stats['errors'] else '• لا توجد أخطاء'}"""
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    try:
        await create_backup()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("✅ تم إنشاء نسخة احتياطية مشفرة جديدة.", reply_markup=kb)
        else:
            await update.message.reply_text("✅ تم إنشاء نسخة احتياطية مشفرة جديدة.", reply_markup=kb)
    except Exception as e:
        error_id = log_error(e, {'user_id': uid, 'action': 'admin_backup'})
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text(f"❌ فشل إنشاء النسخة (الرمز: `{error_id}`)", reply_markup=kb)
        else:
            await update.message.reply_text(f"❌ فشل إنشاء النسخة (الرمز: `{error_id}`)", reply_markup=kb)

async def admin_restore_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    backups = await list_backups()
    if not backups:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد نسخ احتياطية.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد نسخ احتياطية.", reply_markup=kb)
        return
    kb = []
    for b in backups[:10]:
        kb.append([InlineKeyboardButton(b.name, callback_data=f"{CallbackData.ADMIN_RESTORE_BACKUP_SELECT_PREFIX}{b.name}")])
    kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)])
    if query:
        await query.edit_message_text("📂 **اختر النسخة الاحتياطية للاستعادة:**", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text("📂 **اختر النسخة الاحتياطية للاستعادة:**", reply_markup=InlineKeyboardMarkup(kb))

async def admin_restore_backup_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    backup_name = query.data.split(":")[-1] if query else context.user_data.get('restore_backup_name')
    if not backup_name:
        return
    backup_path = BACKUP_DIR / backup_name
    try:
        await restore_backup(backup_path)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("✅ تم استعادة النسخة الاحتياطية المشفرة.", reply_markup=kb)
        else:
            await update.message.reply_text("✅ تم استعادة النسخة الاحتياطية المشفرة.", reply_markup=kb)
    except Exception as e:
        error_id = log_error(e, {'user_id': uid, 'backup': backup_name})
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text(f"❌ فشل الاستعادة (الرمز: `{error_id}`)", reply_markup=kb)
        else:
            await update.message.reply_text(f"❌ فشل الاستعادة (الرمز: `{error_id}`)", reply_markup=kb)

async def admin_backup_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    auto = await db_get_auto_backup()
    status = "مفعل" if auto else "معطل"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تبديل النسخ التلقائي", callback_data=CallbackData.ADMIN_TOGGLE_AUTO_BACKUP)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    text = f"⚙️ **إعدادات النسخ الاحتياطي**\n━━━━━━━━━━━━━━━━━━━━━━\n• النسخ التلقائي: {status}\n• تشفير النسخ: ✅ مفعل\n• الحد الأقصى للنسخ: {MAX_BACKUPS}\n\nيمكنك تبديل الحالة بالزر أدناه."
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_toggle_auto_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    auto = await db_get_auto_backup()
    new_auto = not auto
    await db_set_auto_backup(new_auto)
    status = "مفعل" if new_auto else "معطل"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_BACKUP_SETTINGS)]])
    if query:
        await query.edit_message_text(f"✅ تم تغيير إعداد النسخ التلقائي إلى: {status}", reply_markup=kb)
    else:
        await update.message.reply_text(f"✅ تم تغيير إعداد النسخ التلقائي إلى: {status}", reply_markup=kb)

async def admin_change_interval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    current = await db_get_publish_interval()
    current_min = current // 60
    context.user_data['state'] = UserState.WAITING_INTERVAL_MINUTES
    context.user_data['admin_interval'] = True
    msg = f"⏱️ **وقت النشر العام الحالي:** {current_min} دقيقة\n\n📌 **ملاحظة:** هذا الإعداد يؤثر على الفاصل الزمني بين دورات النشر.\nأرسل العدد الجديد من الدقائق (الحد الأدنى 1 دقيقة، الحد الأقصى 1440 دقيقة = 24 ساعة):"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def admin_send_update_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_UPDATE_TEXT
    msg = "📢 أرسل نص التحديث الذي تريد نشره في قناة التحديثات:"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def admin_set_update_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_UPDATE_CHANNEL
    msg = """⚙️ **تعيين قناة التحديثات**

📢 أرسل معرف قناة التحديثات:

• `@username` (مثل: @my_channel)
• أو المعرف الرقمي (مثل: -1001234567890)

⚠️ **تنبيهات مهمة:**
• تأكد من أن البوت مشرف في القناة
• تأكد من أن البوت لديه صلاحية الإرسال
• القناة يجب أن تكون عامة (Public)"""
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def admin_show_update_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    channel = await db_get_updates_channel()
    if channel:
        text = f"📢 **قناة التحديثات الحالية:**\n`@{channel}`"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 فتح القناة", url=f"https://t.me/{channel}")],
            [InlineKeyboardButton("🔄 تغيير القناة", callback_data=CallbackData.ADMIN_SET_UPDATE_CHANNEL)],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
        ])
    else:
        text = "📢 **لم يتم تعيين قناة تحديثات بعد**"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ تعيين قناة", callback_data=CallbackData.ADMIN_SET_UPDATE_CHANNEL)],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
        ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_updates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    channel = await db_get_updates_channel()
    text = f"📢 **قناة التحديثات الحالية:** @{channel}\n\nيمكنك تغييرها باستخدام زر '⚙️ قناة التحديثات'"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_force_subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    enabled = await db_get_force_subscribe_status()
    new_status = not enabled
    await db_set_force_subscribe_status(new_status)
    status_text = "مفعل" if new_status else "معطل"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text(f"✅ تم {status_text} الاشتراك الإجباري.", reply_markup=kb)
    else:
        await update.message.reply_text(f"✅ تم {status_text} الاشتراك الإجباري.", reply_markup=kb)

async def admin_set_force_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_FORCE_CHANNEL
    msg = "⚙️ أرسل معرف قناة الاشتراك الإجباري (مثال: @channel_username):"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def admin_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_BROADCAST
    msg = "📨 أرسل النص الذي تريد إرساله إلى جميع المستخدمين:"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def admin_confirm_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    broadcast_text = context.user_data.get('broadcast_text', '')
    if not broadcast_text:
        if query:
            await query.edit_message_text("❌ لا يوجد نص للإرسال")
        else:
            await update.message.reply_text("❌ لا يوجد نص للإرسال")
        return
    dangerous_patterns = [r'<script', r'javascript:', r'data:', r'vbscript:', r'<\?php', r'<%', r'{%']
    for pattern in dangerous_patterns:
        if re.search(pattern, broadcast_text, re.IGNORECASE):
            if query:
                await query.edit_message_text("❌ النص يحتوي على كود ضار! تم منع الإرسال.")
            else:
                await update.message.reply_text("❌ النص يحتوي على كود ضار! تم منع الإرسال.")
            return
    if len(broadcast_text) > 4000:
        if query:
            await query.edit_message_text("❌ النص طويل جداً (الحد الأقصى 4000 حرف)")
        else:
            await update.message.reply_text("❌ النص طويل جداً (الحد الأقصى 4000 حرف)")
        return
    if query:
        await query.edit_message_text("📨 جاري الإرسال... يرجى الانتظار")
    else:
        await update.message.reply_text("📨 جاري الإرسال... يرجى الانتظار")

    async def _get_active_users(conn):
        cur = await conn.execute("SELECT user_id FROM users WHERE banned = 0")
        return [row[0] for row in await cur.fetchall()]
    users = await execute_db(_get_active_users)
    sent = 0
    failed = 0
    if not users:
        if query:
            await query.edit_message_text("📭 لا يوجد مستخدمين نشطين لإرسال الرسالة لهم.")
        else:
            await update.message.reply_text("📭 لا يوجد مستخدمين نشطين لإرسال الرسالة لهم.")
        return

    sem = asyncio.Semaphore(20)
    async def send_one(user_id):
        async with sem:
            try:
                await safe_send_markdown(context.bot, user_id, broadcast_text)
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
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

async def admin_support_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    tickets = await db_get_all_tickets(limit=20)
    if not tickets:
        if query:
            await query.edit_message_text("📭 لا توجد تذاكر دعم مسجلة")
        else:
            await update.message.reply_text("📭 لا توجد تذاكر دعم مسجلة")
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
        text += f"\n{status_icon} #{ticket_num} | 👤 {username}\n🆔 `{uid_u}` | 📅 {created_str}\n📝 {msg_preview}\n💡 `/support_reply {uid_u} نص الرد`\n━━━━━━━━━━━━━━━━━━━━━━\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_delete_all_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    confirm_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، احذف الكل", callback_data=CallbackData.ADMIN_CONFIRM_DELETE_TICKETS),
         InlineKeyboardButton("❌ لا، إلغاء", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    if query:
        await query.edit_message_text("⚠️ **تأكيد حذف جميع التذاكر**\n\nهل أنت متأكد من حذف جميع تذاكر الدعم؟", reply_markup=confirm_kb)
    else:
        await update.message.reply_text("⚠️ **تأكيد حذف جميع التذاكر**\n\nهل أنت متأكد من حذف جميع تذاكر الدعم؟", reply_markup=confirm_kb)

async def admin_confirm_delete_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    count = await db_delete_all_tickets()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text(f"✅ تم حذف {count} تذكرة بنجاح.", reply_markup=kb)
    else:
        await update.message.reply_text(f"✅ تم حذف {count} تذكرة بنجاح.", reply_markup=kb)

async def admin_manage_sendcode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    allowed_user = await db_get_allowed_sendcode_user()
    if allowed_user:
        current_text = f"👤 المستخدم الحالي المصرح له بـ /sendcode:\n`{allowed_user}`"
    else:
        current_text = "📭 لم يتم تعيين مستخدم مصرح له بـ /sendcode."
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ تعيين مستخدم جديد", callback_data=CallbackData.ADMIN_SET_SENDCODE_USER)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    if query:
        await safe_edit_markdown(query, current_text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, current_text, reply_markup=keyboard)

async def admin_set_sendcode_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_SENDCODE_USER
    msg = "➕ أرسل معرف المستخدم (user_id) الذي تريد منحه صلاحية استخدام أمر /sendcode:"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def admin_show_log_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    log_ch = await db_get_log_channel_id()
    if log_ch:
        text = f"📋 **قناة التقارير الحالية:**\n`{log_ch}`\n\nيمكنك تغييرها باستخدام زر 'تعيين قناة التقارير'."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await safe_edit_markdown(query, text, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=kb)
    else:
        text = "📋 **لم يتم تعيين قناة تقارير بعد.**\nاستخدم زر 'تعيين قناة التقارير' لتعيينها."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text(text, reply_markup=kb)
        else:
            await update.message.reply_text(text, reply_markup=kb)

async def admin_set_log_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_LOG_CHANNEL
    msg = "📢 **تعيين قناة التقارير**\n\nأرسل معرف القناة (ID) أو معرف المستخدم (@username) للقناة التي تريد استقبال التقارير فيها.\n\nمثال: `-1001234567890` أو `@channel_username`\n\n⚠️ تأكد من أن البوت مشرف في القناة ولديه صلاحية إرسال الرسائل."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

async def admin_replies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    msg = "💬 **إدارة ردود المجموعة**"
    if query:
        await query.edit_message_text(msg, reply_markup=get_replies_keyboard())
    else:
        await update.message.reply_text(msg, reply_markup=get_replies_keyboard())

async def admin_add_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_KEYWORD
    msg = "📝 **إضافة رد تلقائي**\n\nأرسل الكلمة المفتاحية (مثل: مرحبا، السلام عليكم، كيف حالك):"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def admin_list_replies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    replies = await db_get_all_replies()
    if not replies:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_REPLIES)]])
        if query:
            await query.edit_message_text("📭 لا توجد ردود مسجلة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد ردود مسجلة.", reply_markup=kb)
        return
    text = "💬 **قائمة الردود التلقائية**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    for kw, rep in replies[:30]:
        short_rep = rep[:40] + "..." if len(rep) > 40 else rep
        text += f"• **{kw}** → {short_rep}\n"
        keyboard.append([InlineKeyboardButton(f"🗑️ حذف {kw}", callback_data=f"admin_del_reply_{kw}")])
    keyboard.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_REPLIES)])
    if query:
        await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_del_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
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
        msg = "🗑️ **حذف رد تلقائي**\n\nأرسل الكلمة المفتاحية لحذف ردها:"
        if query:
            await query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)

async def admin_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    msg = "🚫 **إدارة الكلمات المحظورة على مستوى البوت (لجميع المجموعات)**"
    if query:
        await query.edit_message_text(msg, reply_markup=get_banned_words_admin_keyboard())
    else:
        await update.message.reply_text(msg, reply_markup=get_banned_words_admin_keyboard())

async def admin_add_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_GLOBAL_BANNED_WORD
    msg = "➕ أرسل الكلمة التي تريد حظرها على مستوى البوت:"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def admin_list_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    words = await db_get_banned_words(-1)
    if not words:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_BANNED_WORDS)]])
        if query:
            await query.edit_message_text("📭 لا توجد كلمات محظورة عامة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد كلمات محظورة عامة.", reply_markup=kb)
        return
    text = "🚫 **الكلمات المحظورة عامة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    for w, by, at in words[:20]:
        text += f"• `{w}` (أضيف بواسطة {by})\n"
        keyboard.append([InlineKeyboardButton(f"🗑️ حذف {w}", callback_data=f"admin_del_banned_word_{w}")])
    keyboard.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_BANNED_WORDS)])
    if query:
        await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_remove_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_REMOVE_GLOBAL_BANNED_WORD
    msg = "🗑️ أرسل الكلمة التي تريد حذفها من الكلمات المحظورة العامة:"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def admin_del_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    word = query.data.replace("admin_del_banned_word_", "") if query else context.user_data.get('del_banned_word')
    if not word:
        return
    async def _remove_global_word(conn):
        await conn.execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", (word, -1))
        await conn.commit()
    await execute_db(_remove_global_word)
    if query:
        await query.answer(f"✅ تم حذف {word}", show_alert=True)
    else:
        await update.message.reply_text(f"✅ تم حذف {word}")
    await admin_list_banned_words_callback(update, context)

# ===================== معالجات الكولباك لحظر القنوات والمجموعات =====================
async def admin_toggle_channel_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
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
    if query:
        await query.answer(f"✅ تم تغيير حالة القناة إلى: {status_text}", show_alert=True)
    await admin_all_channels_callback(update, context)

async def admin_toggle_group_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
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
    if query:
        await query.answer(f"✅ تم تغيير حالة المجموعة إلى: {status_text}", show_alert=True)
    await admin_groups_callback(update, context)

# ===================== معالجات الكولباك للردود التلقائية =====================
async def auto_reply_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split(":")[-1])
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    new_status = await db_toggle_auto_reply(chat_id)
    settings = await db_get_auto_reply_settings(chat_id)
    status_text = "🟢 مفعل" if new_status else "🔴 معطل"
    await query.edit_message_text(
        f"✅ تم تغيير حالة الردود التلقائية إلى: {status_text}",
        reply_markup=get_auto_reply_keyboard(chat_id, settings)
    )

async def auto_reply_admins_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split(":")[-1])
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    settings = await db_get_auto_reply_settings(chat_id)
    new_status = not settings['only_admins']
    await db_set_auto_reply_only_admins(chat_id, new_status)
    settings = await db_get_auto_reply_settings(chat_id)
    admin_text = "👑 مشرفين فقط" if new_status else "👥 الجميع"
    await safe_edit_markdown(query,
        f"✅ تم تغيير وضع الردود إلى: {admin_text}",
        reply_markup=get_auto_reply_keyboard(chat_id, settings)
    )

async def auto_reply_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split(":")[-1])
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، إعادة تعيين", callback_data=f"auto_reply_confirm_reset:{chat_id}")],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"auto_reply_cancel:{chat_id}")]
    ])
    await query.edit_message_text(
        "⚠️ **تأكيد إعادة التعيين**\n\nسيتم حذف جميع الردود المخصصة في هذه المجموعة وإعادة تعيين الإعدادات إلى الافتراضية.\nالردود المدمجة (200 رد) ستبقى كما هي.\n\nهل أنت متأكد؟",
        reply_markup=keyboard
    )

async def auto_reply_confirm_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split(":")[-1])
    user_id = update.effective_user.id
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
    await query.edit_message_text(
        "✅ **تم إعادة تعيين الردود بنجاح!**\n\n• تم حذف جميع الردود المخصصة\n• تم تفعيل الردود التلقائية\n• وضع الردود: الجميع\n• 200 رد مدمج ما زالت تعمل",
        reply_markup=get_auto_reply_keyboard(chat_id, settings)
    )

async def auto_reply_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split(":")[-1])
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    settings = await db_get_auto_reply_settings(chat_id)
    await query.edit_message_text(
        "❌ تم إلغاء إعادة التعيين",
        reply_markup=get_auto_reply_keyboard(chat_id, settings)
    )

async def auto_reply_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split(":")[-1])
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    async def _get_stats(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM group_replies WHERE keyword LIKE ?", (f"{chat_id}:%",))
        custom_count = (await cur.fetchone())[0]
        return {'custom_replies': custom_count, 'embedded_replies': len(ALL_REPLIES), 'total_replies': custom_count + len(ALL_REPLIES)}
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

📌 **ملاحظة:** الردود المدمجة (200 رد) لا يمكن حذفها، ولكن يمكن تعطيلها."""
    await safe_edit_markdown(query,text, reply_markup=get_auto_reply_keyboard(chat_id, settings))

async def user_auto_reply_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split(":")[-1])
    current_status = await db_get_user_auto_reply_status(user_id)
    new_status = not current_status
    await db_set_user_auto_reply_status(user_id, new_status)
    status_text = "🟢 مفعل" if new_status else "🔴 معطل"
    await query.edit_message_text(
        f"✅ تم تغيير حالة الردود التلقائية إلى: {status_text}",
        reply_markup=get_user_auto_reply_keyboard(user_id, new_status)
    )

async def admin_auto_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    groups = await db_get_user_groups(user_id)
    if not groups:
        await query.edit_message_text("📭 لا توجد مجموعات مسجلة.\nأضف البوت إلى مجموعة واجعلها نشطة.")
        return
    keyboard = []
    for chat_id, chat_name, username, banned in groups:
        settings = await db_get_auto_reply_settings(chat_id)
        status = "🟢" if settings['enabled'] else "🔴"
        keyboard.append([InlineKeyboardButton(f"{status} {chat_name[:30]}", callback_data=f"admin_auto_reply_select:{chat_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)])
    await query.edit_message_text(
        "📝 **إدارة الردود التلقائية**\n\nاختر مجموعة للتحكم في إعدادات الردود:\n🟢 = مفعل  |  🔴 = معطل",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_auto_reply_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split(":")[-1])
    settings = await db_get_auto_reply_settings(chat_id)
    async def _get_name(conn):
        cur = await conn.execute("SELECT chat_name FROM bot_groups WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        return row[0] if row else str(chat_id)
    group_name = await execute_db(_get_name)
    await query.edit_message_text(
        f"📝 **إعدادات الردود: {group_name}**\n\nاختر الإعداد المطلوب:",
        reply_markup=get_auto_reply_keyboard(chat_id, settings)
    )

# ===================== معالجات الكولباك لإعدادات NSFW =====================
async def nsfw_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
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
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])

    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def nsfw_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return

    global NSFW_ENABLED
    NSFW_ENABLED = not NSFW_ENABLED

    os.environ["NSFW_ENABLED"] = "True" if NSFW_ENABLED else "False"

    await nsfw_settings_callback(update, context)

async def nsfw_threshold_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return

    context.user_data['state'] = UserState.WAITING_NSFW_THRESHOLD
    msg = """📊 **تغيير نسبة حساسية كشف NSFW**

أرسل النسبة المئوية المطلوبة (من 0 إلى 100):
• 70% = حساسية متوسطة (افتراضي)
• 50% = حساسية عالية (يكتشف محتوى أقل وضوحاً)
• 90% = حساسية منخفضة (يكتشف محتوى واضحاً فقط)

مثال: أرسل `75` أو `80`

⚠️ **تنبيه:** النسبة الأقل تزيد من احتمالية الحظر الخاطئ."""

    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

# ===================== معالجات الكولباك للمسابقات =====================
async def contests_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update or not update.effective_user:
            logger.error("update أو effective_user غير موجود")
            return

        user_id = update.effective_user.id

        contests = []
        try:
            contests = await db_get_active_contests_with_participants(limit=10)
        except Exception as e:
            logger.error(f"خطأ في جلب المسابقات: {e}")
            contests = []

        if not contests:
            text = "📭 لا توجد مسابقات نشطة حالياً."
            if update.callback_query:
                try:
                    await safe_edit_markdown(update.callback_query, text)
                except:
                    await update.callback_query.edit_message_text(text)
            else:
                await safe_send_markdown(context.bot, user_id, text)
            return

        text = "🏆 **المسابقات النشطة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        keyboard = []

        for contest in contests:
            try:
                if len(contest) < 6:
                    continue
                cid = contest[0]
                title = contest[1] or "بدون عنوان"
                desc = contest[2] or ""
                prize = contest[3] or "غير محددة"
                end_date = contest[4]
                participants = contest[5] if len(contest) > 5 else 0
                contest_type = contest[6] if len(contest) > 6 else 'raffle'

                try:
                    end_dt = datetime.fromisoformat(end_date)
                    days_left = (end_dt - utc_now()).days
                    time_left = f"⏳ متبقي {days_left} يوم" if days_left > 0 else "🔴 انتهت"
                except:
                    time_left = "📅 تاريخ غير صحيح"
                    days_left = 0

                try:
                    participated = await db_get_user_participation(user_id, cid)
                except Exception as e:
                    logger.error(f"خطأ في db_get_user_participation للمستخدم {user_id} والمسابقة {cid}: {e}")
                    participated = None

                status_icon = "✅" if participated else "📝"

                type_icon = "📝" if contest_type == 'quiz' else "🎲" if contest_type == 'raffle' else "🗳️" if contest_type == 'vote' else "📤"
                text += f"📌 **{title}** {type_icon}\n"
                text += f"📝 {(desc)[:100]}{'...' if len(desc) > 100 else ''}\n"
                text += f"🎁 الجائزة: {prize}\n"
                text += f"👥 المشاركون: {participants}\n"
                text += f"🕐 {time_left}\n"
                text += f"━━━━━━━━━━━━━━━━━━━━━━\n"

                if not participated and days_left > 0:
                    keyboard.append([InlineKeyboardButton(
                        f"{status_icon} شارك في {title[:20]}",
                        callback_data=f"{CallbackData.CONTEST_JOIN_PREFIX}{cid}"
                    )])
            except Exception as e:
                logger.error(f"خطأ في معالجة مسابقة: {e}")
                continue

        keyboard.append([InlineKeyboardButton("🏆 الفائزون السابقون", callback_data=CallbackData.CONTEST_WINNERS)])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])

        if update.callback_query:
            try:
                await safe_edit_markdown(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard))
            except:
                await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await safe_send_markdown(context.bot, user_id, text, reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        error_id = log_error(e, {
            'user_id': update.effective_user.id if update and update.effective_user else None,
            'chat_id': update.effective_chat.id if update and update.effective_chat else None,
        })
        msg = f"❌ حدث خطأ أثناء تحميل المسابقات (الرمز: `{error_id}`).\nيرجى المحاولة مرة أخرى لاحقاً."
        try:
            if update.callback_query:
                await safe_edit_markdown(update.callback_query, msg)
            else:
                await safe_send_markdown(context.bot, user_id, msg)
        except:
            try:
                if update.callback_query:
                    await update.callback_query.edit_message_text("❌ حدث خطأ أثناء تحميل المسابقات.")
                else:
                    await context.bot.send_message(chat_id=user_id, text="❌ حدث خطأ أثناء تحميل المسابقات.")
            except:
                pass

async def contests_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except:
            pass
    await contests_command_handler(update, context)

async def contest_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    try:
        await query.answer()
    except:
        pass

    user_id = update.effective_user.id

    try:
        contest_id = int(query.data.split(":")[-1])
    except (ValueError, IndexError):
        try:
            await query.edit_message_text("❌ بيانات غير صالحة.")
        except:
            pass
        return

    try:
        contest = await db_get_contest(contest_id)
        if not contest:
            try:
                await query.edit_message_text("❌ المسابقة غير موجودة.")
            except:
                pass
            return

        if contest['status'] != 'active':
            try:
                await query.edit_message_text("❌ هذه المسابقة غير متاحة حالياً.")
            except:
                pass
            return

        try:
            end_date = datetime.fromisoformat(contest['end_date'])
            if end_date < utc_now():
                try:
                    await query.edit_message_text("❌ هذه المسابقة قد انتهت.")
                except:
                    pass
                return
        except:
            pass

        participation = await db_get_user_participation(user_id, contest_id)
        if participation:
            try:
                await query.edit_message_text("✅ أنت مشترك بالفعل في هذه المسابقة!")
            except:
                pass
            return

        context.user_data['contest_join_id'] = contest_id
        context.user_data['state'] = UserState.WAITING_CONTEST_ANSWER

        msg = (
            f"📝 **المشاركة في المسابقة: {contest['title']}**\n\n"
            f"📌 أرسل إجابتك (نص) أو اضغط /skip للمشاركة بدون إجابة.\n"
            f"⏳ يمكنك تعديل إجابتك قبل انتهاء المسابقة.\n"
            f"📝 نوع المسابقة: {contest.get('contest_type', 'raffle')}"
        )
        try:
            await query.edit_message_text(msg, parse_mode="MarkdownV2")
        except:
            await query.edit_message_text(msg)

    except Exception as e:
        error_id = log_error(e, {'user_id': user_id, 'contest_id': contest_id})
        try:
            await query.edit_message_text(f"❌ حدث خطأ أثناء المشاركة (الرمز: `{error_id}`).")
        except:
            pass

async def contest_winners_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        if query:
            await query.answer()
    except:
        pass
    user_id = update.effective_user.id
    try:
        winners = await db_get_contest_winners(limit=10)
        if not winners:
            if query:
                try:
                    await query.edit_message_text("🏆 لا يوجد فائزون سابقون.")
                except:
                    pass
            else:
                await safe_send_markdown(context.bot, user_id, "🏆 لا يوجد فائزون سابقون.")
            return
        text = "🏆 **الفائزون السابقون**\n━━━━━━━━━━━━━━━━━━━━━━\n"
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
        if query:
            try:
                await safe_edit_markdown(query, text, reply_markup=keyboard)
            except:
                await query.edit_message_text(text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)
    except Exception as e:
        error_id = log_error(e, {'user_id': user_id})
        if query:
            try:
                await query.edit_message_text(f"❌ حدث خطأ أثناء عرض الفائزين (الرمز: `{error_id}`).")
            except:
                pass
        else:
            await safe_send_markdown(context.bot, user_id, f"❌ حدث خطأ أثناء عرض الفائزين (الرمز: `{error_id}`).")

async def contests_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await contests_command_handler(update, context)

async def create_contest_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_CONTEST_TITLE
    await update.message.reply_text("📝 **إنشاء مسابقة جديدة**\n\nأرسل **عنوان** المسابقة:")

async def declare_winner_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📝 **الاستخدام:**\n`/declare_winner معرف_المسابقة معرف_المستخدم`\n\nمثال: `/declare_winner 5 123456789`")
        return
    try:
        contest_id = int(args[0])
        winner_id = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ معرف غير صالح.")
        return
    contest = await db_get_contest(contest_id)
    if not contest:
        await update.message.reply_text("❌ المسابقة غير موجودة.")
        return
    if contest['status'] != 'active':
        await update.message.reply_text("❌ هذه المسابقة قد انتهت.")
        return
    participation = await db_get_user_participation(winner_id, contest_id)
    if not participation:
        await update.message.reply_text("❌ هذا المستخدم ليس مشاركاً في المسابقة.")
        return
    success = await db_set_contest_winner(contest_id, winner_id)
    if success:
        await update.message.reply_text(
            f"✅ **تم إعلان الفائز بنجاح!**\n\n"
            f"📌 المسابقة: {contest['title']}\n"
            f"👤 الفائز: `{winner_id}`\n"
            f"🎁 الجائزة: {contest['prize']}"
        )
        try:
            await context.bot.send_message(
                winner_id,
                f"🏆 **تهانينا!**\nلقد فزت في مسابقة **{contest['title']}**!\n🎁 جائزتك: {contest['prize']}"
            )
        except:
            pass
        level_data = await db_get_user_level(winner_id)
        await db_update_user_level(winner_id, level_data['points'] + 50, level_data['level'])
    else:
        await update.message.reply_text("❌ فشل إعلان الفائز، حاول مرة أخرى.")

async def admin_create_contest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except:
            pass

    user_id = update.effective_user.id

    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        if query:
            try:
                await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
            except:
                pass
        return

    context.user_data['state'] = UserState.WAITING_CONTEST_TITLE
    msg = "📝 **إنشاء مسابقة جديدة**\n\nأرسل **عنوان** المسابقة:"

    if query:
        try:
            await query.edit_message_text(msg, parse_mode="MarkdownV2")
        except:
            try:
                await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="MarkdownV2")
            except:
                pass
    else:
        try:
            await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="MarkdownV2")
        except:
            pass

async def admin_declare_winner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except:
            pass

    user_id = update.effective_user.id

    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        if query:
            try:
                await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
            except:
                pass
        return

    msg = "📝 **إعلان فائز في مسابقة**\n\nاستخدم الأمر:\n`/declare_winner معرف_المسابقة معرف_المستخدم`\n\nمثال: `/declare_winner 5 123456789`\n\n📌 لعرض المسابقات النشطة استخدم `/contests`"

    if query:
        try:
            await query.edit_message_text(msg, parse_mode="MarkdownV2")
        except:
            try:
                await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="MarkdownV2")
            except:
                pass
    else:
        try:
            await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="MarkdownV2")
        except:
            pass

# ===================== معالجات الكولباك للغة =====================
async def lang_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if query:
        lang = query.data.split("_")[1] if "_" in query.data else None
    else:
        lang = context.user_data.get('lang_set')
    if not lang:
        if query:
            await query.edit_message_text("❌ لم يتم تحديد اللغة")
        else:
            await update.message.reply_text("❌ لم يتم تحديد اللغة")
        return
    await set_user_language(uid, lang)
    lang_names = {
        'ar': 'العربية 🇸🇦',
        'en': 'English 🇬🇧',
        'fr': 'Français 🇫🇷',
        'tr': 'Türkçe 🇹🇷',
        'zh': '中文 🇨🇳',
        'ru': 'Русский 🇷🇺',
        'de': 'Deutsch 🇩🇪',
        'es': 'Español 🇪🇸',
        'it': 'Italiano 🇮🇹',
        'pt': 'Português 🇵🇹',
        'ja': '日本語 🇯🇵',
        'ko': '한국어 🇰🇷'
    }
    lang_name = lang_names.get(lang, lang)
    kb, title, active_channel = await get_main_keyboard(uid)
    if active_channel:
        context.user_data['active_channel'] = active_channel
        await db_set_active_channel(uid, active_channel)
    if query:
        await safe_edit_markdown(query, f"✅ تم تغيير اللغة إلى {lang_name}\n\n{title}", reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, f"✅ تم تغيير اللغة إلى {lang_name}\n\n{title}", reply_markup=kb)

async def handle_text_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    data = query.data if query else context.user_data.get('text_callback_data')
    if not data:
        return
    if data == "rank":
        data_rank = await get_rank(uid)
        points = data_rank['points']
        level = data_rank['level']
        next_points = LEVEL_REQUIREMENTS.get(level + 1, points)
        points_needed = next_points - points if next_points > points else 0
        text = f"📊 **رتبتك الحالية**\n━━━━━━━━━━━━━━\n👤 {query.from_user.first_name if query else '👤'}\n⭐ **المستوى:** {level}\n📈 **النقاط:** {points}\n📌 **المتبقي للمستوى التالي:** {points_needed}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]])
        if query:
            await safe_edit_markdown(query, text, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=kb)
    elif data == "top":
        top_users = await get_top_users(10)
        if not top_users:
            msg = "📭 لا توجد نقاط مسجدة بعد."
            if query:
                await query.edit_message_text(msg)
            else:
                await update.message.reply_text(msg)
            return
        text = "🏆 **أفضل 10 مستخدمين**\n━━━━━━━━━━━━━━\n"
        for idx, (uid_user, points, level) in enumerate(top_users, 1):
            try:
                user = await context.bot.get_chat(uid_user)
                name = user.first_name or str(uid_user)
            except:
                name = str(uid_user)
            text += f"{idx}. {name} → المستوى {level} ({points} نقطة)\n"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]])
        if query:
            await safe_edit_markdown(query, text, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=kb)
    elif data == "schedule_post":
        context.user_data['state'] = UserState.WAITING_SCHEDULE_POST
        msg = "📝 **جدولة منشور جديد**\n\nأرسل المنشور بالصيغة التالية:\n`YYYY-MM-DD HH:MM نص المنشور`\n\nمثال: `2024-12-31 20:00 مرحباً بالجميع!`\n\n🕐 الوقت بتوقيت مكة المكرمة"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]])
        if query:
            await query.edit_message_text(msg, parse_mode="MarkdownV2", reply_markup=kb)
        else:
            await update.message.reply_text(msg, parse_mode="MarkdownV2", reply_markup=kb)
    elif data == "language":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("العربية 🇸🇦", callback_data="lang_ar"),
             InlineKeyboardButton("English 🇬🇧", callback_data="lang_en")],
            [InlineKeyboardButton("Français 🇫🇷", callback_data="lang_fr"),
             InlineKeyboardButton("Türkçe 🇹🇷", callback_data="lang_tr")],
            [InlineKeyboardButton("中文 🇨🇳", callback_data="lang_zh"),
             InlineKeyboardButton("Русский 🇷🇺", callback_data="lang_ru")],
            [InlineKeyboardButton("Deutsch 🇩🇪", callback_data="lang_de"),
             InlineKeyboardButton("Español 🇪🇸", callback_data="lang_es")],
            [InlineKeyboardButton("Italiano 🇮🇹", callback_data="lang_it"),
             InlineKeyboardButton("Português 🇵🇹", callback_data="lang_pt")],
            [InlineKeyboardButton("日本語 🇯🇵", callback_data="lang_ja"),
             InlineKeyboardButton("한국어 🇰🇷", callback_data="lang_ko")],
            [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
        ])
        if query:
            await query.edit_message_text(get_text(uid, 'welcome'), reply_markup=keyboard)
        else:
            await update.message.reply_text(get_text(uid, 'welcome'), reply_markup=keyboard)
    elif data == CallbackData.CONTESTS_MENU:
        await contests_command_handler(update, context)

# ===================== معالجات الكولباك للإجراءات المتقدمة =====================
async def advanced_actions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if chat_id == 0:
        if query:
            await query.edit_message_text("⚠️ يرجى اختيار مجموعة أولاً باستخدام أمر /security")
        else:
            await update.message.reply_text("⚠️ يرجى اختيار مجموعة أولاً باستخدام أمر /security")
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    msg = "🛠️ **الإجراءات المتقدمة للمجموعة**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر الإجراء المطلوب:"
    if query:
        await safe_edit_markdown(query, msg, reply_markup=get_advanced_group_actions_keyboard(chat_id))
    else:
        await safe_send_markdown(context.bot, uid, msg, reply_markup=get_advanced_group_actions_keyboard(chat_id))

async def group_action_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_BAN_USER
    context.user_data['advanced_chat_id'] = chat_id
    msg = "🚫 **حظر مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /ban\n\nيمكنك إضافة سبب بعد المعرف: `/ban 123456789 السبب`"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_mute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    msg = "🔇 **كتم مستخدم**\n\nاختر مدة الكتم:"
    if query:
        await safe_edit_markdown(query, msg, reply_markup=get_advanced_mute_duration_keyboard(chat_id))
    else:
        await update.message.reply_text(msg, reply_markup=get_advanced_mute_duration_keyboard(chat_id))

async def advanced_mute_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    parts = query.data.split(":") if query else context.user_data.get('mute_duration_data', '').split(":")
    if len(parts) == 3:
        minutes = int(parts[1])
        chat_id = int(parts[2])
        uid = update.effective_user.id
        if not await is_authorized_in_group(context.bot, chat_id, uid):
            if query:
                await query.answer(get_text(uid, 'admin_only'), show_alert=True)
            else:
                await update.message.reply_text(get_text(uid, 'admin_only'))
            return
        context.user_data['mute_minutes'] = minutes
        context.user_data['state'] = UserState.WAITING_MUTE_USER
        context.user_data['advanced_chat_id'] = chat_id
        if minutes == 0:
            msg = "🔇 **كتم دائم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute\n\nيمكنك إضافة سبب: `/mute 123456789 السبب`"
        elif minutes < 60:
            msg = f"🔇 **كتم {minutes} دقيقة**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute\n\nيمكنك إضافة سبب: `/mute 123456789 السبب`"
        elif minutes < 1440:
            msg = f"🔇 **كتم {minutes // 60} ساعة**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute\n\nيمكنك إضافة سبب: `/mute 123456789 السبب`"
        else:
            msg = f"🔇 **كتم {minutes // 1440} يوم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute\n\nيمكنك إضافة سبب: `/mute 123456789 السبب`"
        if query:
            await safe_edit_markdown(query, msg)
        else:
            await update.message.reply_text(msg)

async def group_action_warn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_WARN_USER
    context.user_data['advanced_chat_id'] = chat_id
    msg = "⚠️ **تحذير مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /warn\n\nيمكنك إضافة سبب: `/warn 123456789 السبب`\n\n📌 بعد 3 تحذيرات يتم حظر المستخدم تلقائياً"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_kick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_KICK_USER
    context.user_data['advanced_chat_id'] = chat_id
    msg = "👢 **طرد مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /kick\n\nيمكنك إضافة سبب: `/kick 123456789 السبب`"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_restrict_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_RESTRICT_USER
    context.user_data['advanced_chat_id'] = chat_id
    msg = "🔒 **تقييد مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /restrict\n\n📌 التقييد يمنع المستخدم من إرسال الصور والفيديوهات والملفات"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_pin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_PIN_MESSAGE
    context.user_data['advanced_chat_id'] = chat_id
    msg = "📌 **تثبيت رسالة**\n\nقم بالرد على الرسالة التي تريد تثبيتها ثم أرسل /pin"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_log_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    text = await get_moderation_log(chat_id, 20)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def group_action_unban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_UNBAN_USER
    context.user_data['advanced_chat_id'] = chat_id
    msg = "🔓 **إلغاء حظر مستخدم**\n\nأرسل معرف المستخدم (user_id) لإلغاء حظره:\n`/unban 123456789`"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

# ===================== معالجات الكولباك للوحة التحكم =====================
async def panel_lock_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('panel_chat_id')
    if not chat_id:
        return
    if await is_authorized_in_group(context.bot, chat_id, uid):
        await db_set_chat_lock(chat_id, True, uid)
        if query:
            await safe_edit_markdown(query, get_text(uid, 'locked'))
        else:
            await update.message.reply_text(get_text(uid, 'locked'))
    else:
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))

async def panel_unlock_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('panel_chat_id')
    if not chat_id:
        return
    if await is_authorized_in_group(context.bot, chat_id, uid):
        await db_set_chat_lock(chat_id, False)
        if query:
            await safe_edit_markdown(query, get_text(uid, 'unlocked'))
        else:
            await update.message.reply_text(get_text(uid, 'unlocked'))
    else:
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))

async def panel_close_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.message.delete()

# ===================== معالجات الكولباك للإشتراك الإجباري =====================
async def check_subscribe_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    enabled = await db_get_force_subscribe_status()
    channel = await db_get_force_subscribe_channel()
    if enabled and channel:
        if await is_user_subscribed(context.bot, uid, channel):
            if query:
                await safe_edit_markdown(query, "✅ تم التحقق! أنت مشترك الآن.")
            else:
                await update.message.reply_text("✅ تم التحقق! أنت مشترك الآن.")
            await main_menu_callback(update, context)
        else:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 اشترك", url=f"https://t.me/{channel.lstrip('@')}"),
                 InlineKeyboardButton("🔄 تأكد", callback_data=CallbackData.CHECK_SUBSCRIBE),
                 InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
            ])
            if query:
                await safe_edit_markdown(query, f"❌ لم تشترك في @{channel.lstrip('@')}", reply_markup=kb)
            else:
                await update.message.reply_text(f"❌ لم تشترك في @{channel.lstrip('@')}", reply_markup=kb)
    else:
        if query:
            await safe_edit_markdown(query, "⚠️ الاشتراك الإجباري غير مفعل")
        else:
            await update.message.reply_text("⚠️ الاشتراك الإجباري غير مفعل")

# ===================== معالجات الكولباك للنشر في جميع القنوات =====================
async def publish_all_channels_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    channels = await db_get_channels(uid)
    if not channels:
        if query:
            await query.edit_message_text("📭 لا توجد قنوات للنشر فيها.")
        else:
            await update.message.reply_text("📭 لا توجد قنوات للنشر فيها.")
        return
    if query:
        await query.edit_message_text("📤 جاري النشر في جميع القنوات...")
    else:
        await update.message.reply_text("📤 جاري النشر في جميع القنوات...")
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
        translation_lang = await get_user_translation_language(uid)
        final_text = post['text']
        if translation_lang != 'off' and final_text:
            try:
                translated = await translate_text(final_text, translation_lang)
                if translated and translated != final_text:
                    final_text = f"{final_text}\n\n🌐 {translated}"
            except:
                pass
        try:
            if post['media_type'] == 'photo' and post['media_file_id']:
                await context.bot.send_photo(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
            elif post['media_type'] == 'video' and post['media_file_id']:
                await context.bot.send_video(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
            elif post['media_type'] == 'document' and post['media_file_id']:
                await context.bot.send_document(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
            elif post['media_type'] == 'audio' and post['media_file_id']:
                await context.bot.send_audio(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
            elif post['media_type'] == 'voice' and post['media_file_id']:
                await context.bot.send_voice(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
            elif post['media_type'] == 'animation' and post['media_file_id']:
                await context.bot.send_animation(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
            else:
                await context.bot.send_message(ch_tele_id, final_text)
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
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, result_text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, result_text, reply_markup=keyboard)

# ===================== معالجات الكولباك لإحصائيات القنوات =====================
async def channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    try:
        channel_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('channel_stats_id')
    except:
        channel_db_id = context.user_data.get('channel_stats_id')
    if not channel_db_id:
        if query:
            await query.edit_message_text("⚠️ لم يتم تحديد القناة.")
        else:
            await update.message.reply_text("⚠️ لم يتم تحديد القناة.")
        return
    channels = await db_get_channels(user_id)
    if not any(ch[0] == channel_db_id for ch in channels):
        if query:
            await query.answer("❌ هذه القناة ليست لك", show_alert=True)
        else:
            await update.message.reply_text("❌ هذه القناة ليست لك")
        return
    stats = await db_get_channel_stats(channel_db_id)
    ch_info = await db_get_channel_info(channel_db_id)
    channel_name = ch_info[1] if ch_info else "القناة"
    if stats['total_posts'] == 0:
        text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد منشورات بعد"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{channel_db_id}")],
            [InlineKeyboardButton("📈 نمو القناة", callback_data=f"{CallbackData.CHANNEL_GROWTH}:{channel_db_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
        if query:
            await safe_edit_markdown(query, text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)
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
    text += f"⏱️ متوسط الوقت بين المنشورات: {stats['avg_time_between_posts']} ساعة\n"
    text += f"🕐 أفضل وقت للنشر: {stats['best_publish_hour']}:00\n"
    day_names = ['الأحد', 'الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت']
    text += f"📅 أفضل يوم للنشر: {day_names[stats['best_publish_day']] if stats['best_publish_day'] < 7 else 'غير محدد'}\n"
    text += f"📊 المنشورات اليوم: {stats['published_today']}\n"
    text += f"📊 هذا الأسبوع: {stats['published_this_week']}\n"
    text += f"📊 هذا الشهر: {stats['published_this_month']}\n"
    if stats['most_viewed_post']:
        text += f"\n🏆 **الأكثر مشاهدة:**\n{stats['most_viewed_post']['text']}\n👁️ {stats['most_viewed_post']['views']} مشاهدة\n"
    if stats['least_viewed_post']:
        text += f"\n📉 **الأقل مشاهدة:**\n{stats['least_viewed_post']['text']}\n👁️ {stats['least_viewed_post']['views']} مشاهدة\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{channel_db_id}")],
        [InlineKeyboardButton("📈 نمو القناة", callback_data=f"{CallbackData.CHANNEL_GROWTH}:{channel_db_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def channel_growth_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    try:
        channel_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('channel_stats_id')
    except:
        channel_db_id = context.user_data.get('channel_stats_id')
    if not channel_db_id:
        if query:
            await query.edit_message_text("⚠️ لم يتم تحديد القناة.")
        else:
            await update.message.reply_text("⚠️ لم يتم تحديد القناة.")
        return
    channels = await db_get_channels(user_id)
    if not any(ch[0] == channel_db_id for ch in channels):
        if query:
            await query.answer("❌ هذه القناة ليست لك", show_alert=True)
        else:
            await update.message.reply_text("❌ هذه القناة ليست لك")
        return
    growth = await db_get_channel_growth(channel_db_id, days=30)
    ch_info = await db_get_channel_info(channel_db_id)
    channel_name = ch_info[1] if ch_info else "القناة"
    if not growth['dates']:
        text = f"📈 **نمو {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\nلا توجد بيانات كافية لعرض النمو."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.CHANNEL_STATS}:{channel_db_id}")]
        ])
        if query:
            await safe_edit_markdown(query, text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)
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
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def channel_stats_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await channel_stats_callback(update, context)

async def my_channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    summary = await db_get_channel_stats_summary(user_id)
    if not summary:
        text = "📊 **ملخص قنواتي**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد قنوات مسجلة."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة قناة", callback_data=CallbackData.CHANNELS_ADD)],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
        if query:
            await safe_edit_markdown(query, text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)
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
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

# ===================== معالجات الكولباك للمالك والمشرفين المخفيين =====================
async def register_hidden_owner_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    user = update.effective_user
    if user is None:
        return
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ يعمل فقط في المجموعات")
        return

    chat_id = chat.id
    user_id = user.id

    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return

    if await db_is_hidden_owner(chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'hidden_owner_already'))
        return

    await db_register_hidden_owner_group(chat_id, user_id)
    await update.message.reply_text(get_text(user_id, 'hidden_owner_registered'))

async def add_hidden_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return

    args = context.args
    if len(args) < 1:
        await update.message.reply_text(
            "📝 **الاستخدام:**\n"
            "/add_hidden_admin معرف_المستخدم\n\n"
            "مثال: `/add_hidden_admin 123456789`"
        )
        return

    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح!")
        return

    if target_id == PRIMARY_OWNER_ID:
        await update.message.reply_text("❌ لا يمكن إضافة المطور الأساسي كمشرف مخفي!")
        return

    if target_id == user_id:
        await update.message.reply_text("❌ لا يمكن إضافة نفسك كمشرف مخفي!")
        return

    try:
        member = await context.bot.get_chat_member(chat_id, target_id)
        if member.status in ['left', 'kicked']:
            await update.message.reply_text("❌ المستخدم ليس في المجموعة!")
            return
    except Exception as e:
        await update.message.reply_text(f"❌ لا يمكن العثور على المستخدم: {e}")
        return

    try:
        user = await context.bot.get_chat(target_id)
        if user.is_bot:
            await update.message.reply_text("❌ لا يمكن إضافة بوت كمشرف مخفي!")
            return
    except:
        pass

    if await db_is_hidden_admin(chat_id, target_id):
        await update.message.reply_text(f"⚠️ المستخدم `{target_id}` مشرف مخفي بالفعل!")
        return

    success = await db_add_hidden_admin(chat_id, target_id, user_id)
    if success:
        await update.message.reply_text(get_text(user_id, 'hidden_admin_added').format(target_id))
        await security_audit.log("HIDDEN_ADMIN_ADDED", user_id, {"chat_id": chat_id, "target": target_id}, "HIGH")
        invalidate_auth_cache(chat_id, target_id)
    else:
        await update.message.reply_text("❌ فشل إضافة المشرف المخفي!")

async def remove_hidden_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return

    args = context.args
    if len(args) < 1:
        await update.message.reply_text(
            "📝 **الاستخدام:**\n"
            "/remove_hidden_admin معرف_المستخدم\n\n"
            "مثال: `/remove_hidden_admin 123456789`"
        )
        return

    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح!")
        return

    if target_id == PRIMARY_OWNER_ID:
        await update.message.reply_text("❌ لا يمكن إزالة المطور الأساسي!")
        return

    if not await db_is_hidden_admin(chat_id, target_id):
        await update.message.reply_text(f"⚠️ المستخدم `{target_id}` ليس مشرفاً مخفياً!")
        return

    success = await db_remove_hidden_admin(chat_id, target_id)
    if success:
        await update.message.reply_text(get_text(user_id, 'hidden_admin_removed').format(target_id))
        await security_audit.log("HIDDEN_ADMIN_REMOVED", user_id, {"chat_id": chat_id, "target": target_id}, "HIGH")
        invalidate_auth_cache(chat_id, target_id)
    else:
        await update.message.reply_text("❌ فشل إزالة المشرف المخفي!")

async def list_hidden_admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return

    admins = await db_get_hidden_admins(chat_id)
    if not admins:
        await update.message.reply_text(get_text(user_id, 'no_hidden_admins'))
        return

    text = get_text(user_id, 'hidden_admin_list').format("")
    for admin in admins:
        text += f"👤 المستخدم: `{admin['admin_id']}`\n"
        text += f"➕ أضيف بواسطة: `{admin['added_by']}`\n"
        text += f"🕐 التاريخ: {admin['added_at'][:16]}\n"
        text += "━━━━━━━━━━━━━━━━━━━━━━\n"

    await update.message.reply_text(text, parse_mode="MarkdownV2")

# ===================== دوال التحقق من صلاحية المشرف =====================
async def check_admin_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat is None or update.effective_user is None:
        return False
    if update.effective_chat.type not in ['group', 'supergroup']:
        return False
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    return await is_authorized_in_group(context.bot, chat_id, user_id)

# ===================== معالجات الدفع =====================
async def pre_checkout_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("sub_"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="بيانات غير صالحة")

async def successful_payment_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text(f"✅ **تم تفعيل اشتراكك لمدة {days} يوماً!**\nشكراً لدعمك ❤️", parse_mode="MarkdownV2")

async def ensure_force_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None) -> bool:
    if user_id is None:
        if update.effective_user is None:
            return True
        user_id = update.effective_user.id
    if user_id == PRIMARY_OWNER_ID or await is_bot_admin(user_id):
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
         InlineKeyboardButton("🔄 تأكد من الاشتراك", callback_data=CallbackData.CHECK_SUBSCRIBE)],
        [InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.BACK)]
    ])
    msg = f"🔒 **اشتراك إجباري**\n\nيجب عليك الاشتراك في قناتنا أولاً:\n👉 @{channel.lstrip('@')}\n\nبعد الاشتراك، اضغط على زر التحقق."
    try:
        if update.callback_query:
            if update.callback_query.message.text == msg:
                return False
            await safe_edit_markdown(update.callback_query, msg, reply_markup=keyboard)
        elif update.message:
            await safe_send_markdown(context.bot, user_id, msg, reply_markup=keyboard)
    except Exception:
        pass
    return False

async def is_user_subscribed(bot, user_id, channel):
    if not channel:
        return True
    channel = channel.lstrip('@')
    try:
        member = await bot.get_chat_member(f"@{channel}", user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or ""

    await db_register_user(user_id)
    await db_update_user_cache(user_id, username, first_name)

    if context.args and context.args[0].startswith('ref_'):
        referral_code = context.args[0].replace('ref_', '')
        referrer_id = await db_get_user_by_referral_code(referral_code)
        if referrer_id and referrer_id != user_id:
            success = await db_add_referral(referrer_id, user_id)
            if success:
                reward_days = await db_auto_reward_referral(referrer_id, user_id)
                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=f"🎉 **تهانينا!**\nقام {first_name} بالاشتراك باستخدام رابط إحالتك!\nتم إضافة {reward_days} أيام إلى اشتراكك 🎁",
                        parse_mode="MarkdownV2"
                    )
                except:
                    pass
                welcome_points = await db_get_welcome_bonus_points()
                if welcome_points > 0:
                    level_data = await db_get_user_level(user_id)
                    await db_update_user_level(user_id, level_data['points'] + welcome_points, level_data['level'])

                achievement = await achievement_system(referrer_id, 'first_referral')
                if achievement:
                    try:
                        await context.bot.send_message(chat_id=referrer_id, text=f"🏅 {achievement}")
                    except:
                        pass

    await main_menu_callback(update, context)

# ===================== معالج /sendcode مع مهلة 10 دقائق =====================
async def sendcode_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    allowed_user = await db_get_allowed_sendcode_user()
    if user_id != PRIMARY_OWNER_ID and user_id != allowed_user:
        await safe_send_markdown(context.bot, user_id, "🔒 هذا الأمر للمطور الأساسي أو المستخدمين المصرح لهم فقط.")
        logger.warning(f"⚠️ محاولة استخدام /sendcode من مستخدم غير مصرح: {user_id}")
        await security_audit.log("UNAUTHORIZED_SENDCODE_ATTEMPT", user_id, {}, "CRITICAL")
        return

    if ENABLE_2FA and ADMIN_2FA_SECRET and PYOTP_AVAILABLE:
        if not context.user_data.get('2fa_verified') or time_module.time() - context.user_data.get('2fa_time', 0) > 300:
            secret = ADMIN_2FA_SECRET
            totp = pyotp.TOTP(secret)
            context.user_data['waiting_2fa'] = True
            await update.message.reply_text("🔐 أدخل رمز المصادقة الثنائية (2FA):")
            return

    temp_password = secrets.token_urlsafe(12)
    context.user_data['sendcode_temp_password'] = temp_password
    context.user_data['sendcode_temp_timestamp'] = time_module.time()
    context.user_data['state'] = UserState.WAITING_SENDCODE_PASSWORD

    await update.message.reply_text(
        f"🔐 **تأكيد أمني إضافي**\n\n"
        f"لإرسال الكود، يرجى تأكيد هويتك بإرسال كلمة المرور المؤقتة:\n"
        f"`{temp_password}`\n\n"
        f"⏰ **تنتهي الصلاحية خلال 10 دقائق.**"
    )

async def handle_sendcode_confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    expected_password = context.user_data.get('sendcode_temp_password')
    timestamp = context.user_data.get('sendcode_temp_timestamp', 0)

    if not expected_password:
        await update.message.reply_text("❌ لم يتم طلب إرسال كود")
        context.user_data.pop('state', None)
        return

    SENDCODE_TIMEOUT = 600
    if time_module.time() - timestamp > SENDCODE_TIMEOUT:
        await update.message.reply_text(
            f"❌ انتهت صلاحية كلمة المرور (المهلة {SENDCODE_TIMEOUT // 60} دقائق).\nأعد استخدام الأمر /sendcode."
        )
        context.user_data.pop('sendcode_temp_password', None)
        context.user_data.pop('sendcode_temp_timestamp', None)
        context.user_data.pop('state', None)
        return

    if update.message.text.strip() == expected_password:
        try:
            with open(__file__, 'r', encoding='utf-8') as f:
                content = f.read()
            watermark = f"""# ============================================================
# ORIGINAL_OWNER: {user_id}
# GENERATED_AT: {mecca_now().strftime('%Y-%m-%d %H:%M:%S')}
# SIGNATURE: {hashlib.sha256(f"{user_id}{time_module.time()}{TOKEN}".encode()).hexdigest()[:16]}
# ============================================================
# ⚠️ تحذير: هذا الكود يحتوي على معلومات حساسة
# لا تشاركه مع أي شخص غير موثوق
# ============================================================

"""
            watermarked_content = watermark + content

            temp_dir = tempfile.gettempdir()
            temp_file = os.path.join(temp_dir, f"bot_code_{user_id}_{int(time_module.time())}.py")
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(watermarked_content)

            with open(temp_file, 'rb') as f:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=f,
                    filename=f"relax_bot_secure_{mecca_now().strftime('%Y%m%d')}.py",
                    caption="⚠️ **هذا الكود موقع رقمياً - لا تشاركه مع أي شخص غير موثوق!**\n\n📌 يحتوي على:\n• التوكن والمفاتيح\n• هيكل قاعدة البيانات\n• معلومات حساسة أخرى"
                )

            os.unlink(temp_file)

            await security_audit.log("SENDCODE_EXECUTED", user_id, {"timestamp": mecca_now_iso()}, "CRITICAL")
            await update.message.reply_text("✅ تم إرسال الكود بنجاح على الخاص!")
            logger.info(f"📁 تم إرسال كود البوت للمستخدم {user_id} على الخاص")
        except Exception as e:
            await update.message.reply_text(f"❌ فشل إرسال الكود: {str(e)[:100]}")
            logger.error(f"خطأ في إرسال الكود: {e}")
        context.user_data.pop('sendcode_temp_password', None)
        context.user_data.pop('sendcode_temp_timestamp', None)
        context.user_data.pop('state', None)
    else:
        await update.message.reply_text("❌ كلمة المرور غير صحيحة! تم إلغاء العملية.")
        await security_audit.log("SENDCODE_FAILED_ATTEMPT", user_id, {"attempt": update.message.text[:6]}, "HIGH")
        context.user_data.pop('sendcode_temp_password', None)
        context.user_data.pop('sendcode_temp_timestamp', None)
        context.user_data.pop('state', None)

# ===================== أوامر إضافية =====================
async def language_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("العربية 🇸🇦", callback_data="lang_ar"),
         InlineKeyboardButton("English 🇬🇧", callback_data="lang_en")],
        [InlineKeyboardButton("Français 🇫🇷", callback_data="lang_fr"),
         InlineKeyboardButton("Türkçe 🇹🇷", callback_data="lang_tr")],
        [InlineKeyboardButton("中文 🇨🇳", callback_data="lang_zh"),
         InlineKeyboardButton("Русский 🇷🇺", callback_data="lang_ru")],
        [InlineKeyboardButton("Deutsch 🇩🇪", callback_data="lang_de"),
         InlineKeyboardButton("Español 🇪🇸", callback_data="lang_es")],
        [InlineKeyboardButton("Italiano 🇮🇹", callback_data="lang_it"),
         InlineKeyboardButton("Português 🇵🇹", callback_data="lang_pt")],
        [InlineKeyboardButton("日本語 🇯🇵", callback_data="lang_ja"),
         InlineKeyboardButton("한국어 🇰🇷", callback_data="lang_ko")]
    ])
    await update.message.reply_text(get_text(user_id, 'welcome'), reply_markup=keyboard)

async def syncgroup_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return

    chat_id = update.effective_chat.id
    chat_name = update.effective_chat.title or "بدون اسم"
    user_id = update.effective_user.id

    await db_register_group(chat_id, chat_name, user_id, update.effective_chat.username)
    await db_sync_group_admins(chat_id, context.bot, user_id)

    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"⚠️ **تنبيه:**\n{bot_perms['reason']}\n\nيرجى منح البوت الصلاحيات المطلوبة.")
        return

    if await is_authorized_in_group(context.bot, chat_id, user_id):
        await db_register_hidden_owner_group(chat_id, user_id)

    await update.message.reply_text(
        f"✅ **تم تفعيل المجموعة بنجاح!**\n\n"
        f"📌 اسم المجموعة: {chat_name}\n"
        f"🆔 المعرف: {chat_id}\n"
        f"👤 المضافة بواسطة: {user_id}\n\n"
        f"🔐 استخدم /security لإعدادات الأمان\n"
        f"🛠️ استخدم /panel للوحة التحكم",
        parse_mode="MarkdownV2"
    )

async def security_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return

    chat_id = update.effective_chat.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return

    await security_select_group_callback(update, context)

async def trial_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await trial_callback(update, context)

async def subscribe_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscribe_menu_callback(update, context)

async def help_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_send_markdown(context.bot, user_id, get_text(user_id, 'help'), reply_markup=keyboard)

async def support_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data['support_mode'] = True
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 كتابة تذكرة", callback_data=CallbackData.SUPPORT_TICKET)],
        [InlineKeyboardButton("❓ المساعدة", callback_data=CallbackData.SUPPORT_HELP)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await update.message.reply_text(get_text(user_id, 'support_welcome'), reply_markup=keyboard)

async def support_reply_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != PRIMARY_OWNER_ID and not await is_bot_admin(update.effective_user.id):
        await update.message.reply_text(get_text(update.effective_user.id, 'admin_only'))
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📝 **الاستخدام:**\n`/support_reply user_id نص الرد`", parse_mode="MarkdownV2")
        return
    try:
        target_user_id = int(args[0])
        reply_text = " ".join(args[1:])
        ticket_id = await db_get_last_ticket_id_for_user(target_user_id)
        if ticket_id:
            await db_mark_ticket_replied(ticket_id)
        await context.bot.send_message(chat_id=target_user_id, text=f"📬 **رد على تذكرتك:**\n━━━━━━━━━━━━━━━━━━━━━━\n{reply_text}", parse_mode="MarkdownV2")
        await update.message.reply_text(f"✅ تم إرسال الرد إلى المستخدم {target_user_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل الإرسال: {e}")

async def rank_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_text_callbacks(update, context)

async def top_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_text_callbacks(update, context)

async def developer_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await developer_callback(update, context)

async def updates_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await updates_callback(update, context)

async def stats_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    uid = update.effective_user.id
    if not await ensure_force_subscribe(update, context, uid):
        return
    active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if not active:
        await update.message.reply_text("⚠️ يرجى اختيار قناة أولاً")
        return
    stats = await db_get_channel_stats(active)
    ch_info = await db_get_channel_info(active)
    channel_name = ch_info[1] if ch_info else "القناة"
    if stats['total_posts'] == 0:
        text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد منشورات بعد"
        await safe_send_markdown(context.bot, uid, text)
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
    text += f"⏱️ متوسط الوقت بين المنشورات: {stats['avg_time_between_posts']} ساعة\n"
    text += f"🕐 أفضل وقت للنشر: {stats['best_publish_hour']}:00\n"
    day_names = ['الأحد', 'الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت']
    text += f"📅 أفضل يوم للنشر: {day_names[stats['best_publish_day']] if stats['best_publish_day'] < 7 else 'غير محدد'}\n"
    text += f"📊 المنشورات اليوم: {stats['published_today']}\n"
    text += f"📊 هذا الأسبوع: {stats['published_this_week']}\n"
    text += f"📊 هذا الشهر: {stats['published_this_month']}\n"
    if stats['most_viewed_post']:
        text += f"\n🏆 **الأكثر مشاهدة:**\n{stats['most_viewed_post']['text']}\n👁️ {stats['most_viewed_post']['views']} مشاهدة\n"
    if stats['least_viewed_post']:
        text += f"\n📉 **الأقل مشاهدة:**\n{stats['least_viewed_post']['text']}\n👁️ {stats['least_viewed_post']['views']} مشاهدة\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{active}")],
        [InlineKeyboardButton("📈 نمو القناة", callback_data=f"{CallbackData.CHANNEL_GROWTH}:{active}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def lock_chat_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat is None or update.effective_user is None:
        return
    if update.effective_chat.type == 'private':
        await update.message.reply_text(get_text(update.effective_user.id, 'group_only'))
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    await db_set_chat_lock(chat_id, True, user_id)
    await update.message.reply_text(get_text(user_id, 'locked'), parse_mode="MarkdownV2")

async def unlock_chat_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat is None or update.effective_user is None:
        return
    if update.effective_chat.type == 'private':
        await update.message.reply_text(get_text(update.effective_user.id, 'group_only'))
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    await db_set_chat_lock(chat_id, False)
    await update.message.reply_text(get_text(user_id, 'unlocked'), parse_mode="MarkdownV2")

async def panel_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text(f"🔧 **لوحة تحكم المجموعة**\n━━━━━━━━━━━━━━\n📌 **المجموعة:** {chat.title}\n🔐 **الحالة:** {lock_status_text}\n━━━━━━━━━━━━━━\n\nاستخدم الأزرار للتحكم في قفل وفتح المجموعة والإجراءات المتقدمة", reply_markup=kb, parse_mode="MarkdownV2")

async def schedule_post_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.effective_user is None or update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("📝 **الاستخدام:**\n`/schedule YYYY-MM-DD HH:MM نص المنشور`", parse_mode="MarkdownV2")
        return
    try:
        date_str = args[0]
        time_str = args[1]
        text = " ".join(args[2:])
        mecca_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        if mecca_dt <= mecca_now():
            await update.message.reply_text("❌ **الوقت يجب أن يكون في المستقبل!**", parse_mode="MarkdownV2")
            return
        utc_dt = mecca_to_utc(mecca_dt)
        await db_add_scheduled_post(chat_id, text, utc_dt)
        await update.message.reply_text(f"✅ **تم جدولة المنشور!**\n📅 {date_str} 🕐 {time_str} (بتوقيت مكة)", parse_mode="MarkdownV2")
    except ValueError:
        await update.message.reply_text("❌ صيغة التاريخ أو الوقت غير صحيحة!", parse_mode="MarkdownV2")

async def set_log_channel_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    args = context.args
    if not args and context.user_data.get('state') == UserState.WAITING_LOG_CHANNEL:
        identifier = context.user_data.get('temp_log_channel_identifier')
        if identifier:
            args = [identifier]
    if not args:
        await update.message.reply_text("📝 **الاستخدام:**\n`/set_log_channel معرف_القناة`\n\nمثال: `/set_log_channel -1001234567890`\nأو `/set_log_channel @username`", parse_mode="MarkdownV2")
        return
    identifier = args[0].strip()
    if identifier.startswith('@'):
        identifier = identifier[1:]
    try:
        if identifier.startswith('-100') or identifier.lstrip('-').isdigit():
            chat_id = int(identifier)
        else:
            chat = await context.bot.get_chat(f"@{identifier}")
            chat_id = chat.id
    except Exception as e:
        await update.message.reply_text(f"❌ لا يمكن العثور على القناة: {e}", parse_mode="MarkdownV2")
        return
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        if bot_member.status not in ['administrator', 'creator']:
            await update.message.reply_text("❌ **البوت ليس مشرفاً في هذه القناة.**", parse_mode="MarkdownV2")
            return
        if not bot_member.can_post_messages:
            await update.message.reply_text("❌ **البوت لا يملك صلاحية الإرسال.**", parse_mode="MarkdownV2")
            return
    except Exception as e:
        await update.message.reply_text(f"❌ لا يمكن الوصول للقناة: {e}", parse_mode="MarkdownV2")
        return
    await db_set_log_channel_id(str(chat_id))
    await update.message.reply_text(f"✅ **تم تعيين قناة التقارير بنجاح!**\nمعرف القناة: `{chat_id}`", parse_mode="MarkdownV2")
    try:
        await context.bot.send_message(chat_id, "✅ **تم تفعيل نظام التقارير**")
    except:
        pass
    context.user_data.pop('state', None)
    context.user_data.pop('temp_log_channel_identifier', None)

# ===================== معالجات الكولباك للمجموعات =====================
async def handle_moderation_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        return
    user_id = update.effective_user.id
    chat_id = chat.id
    text = update.message.text.strip() if update.message.text else ""
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"❌ {bot_perms['reason']}")
        return
    args = text.split(maxsplit=1)
    reason = args[1] if len(args) > 1 else ""
    if text.startswith("/ban") and update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        success, msg = await execute_ban(context.bot, chat_id, target_user.id, reason=reason, moderator_id=user_id)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/mute") and update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        minutes = context.user_data.get('mute_minutes', 60)
        success, msg = await execute_mute(context.bot, chat_id, target_user.id, minutes, reason=reason, moderator_id=user_id)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/warn") and update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        success, msg = await execute_warn(context.bot, chat_id, target_user.id, user_id, reason=reason)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/kick") and update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        success, msg = await execute_kick(context.bot, chat_id, target_user.id, reason=reason, moderator_id=user_id)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/restrict") and update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        success, msg = await execute_restrict(context.bot, chat_id, target_user.id, reason=reason, moderator_id=user_id)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/pin") and update.message.reply_to_message:
        success, msg = await execute_pin(context.bot, chat_id, update.message.reply_to_message.message_id)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/unban"):
        parts = text.split()
        if len(parts) >= 2:
            try:
                target_id = int(parts[1])
                success, msg = await execute_unban(context.bot, chat_id, target_id, moderator_id=user_id)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
        else:
            await update.message.reply_text("📝 **الاستخدام:** `/unban معرف_المستخدم`", parse_mode="MarkdownV2")
        return

# ===================== معالجات إضافة البوت =====================
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
            chat_name = chat.title or "بدون اسم"
            await db_register_group(chat.id, chat_name, added_by_id, chat.username)
            chat_type_name = "مجموعة" if chat.type == 'group' else "سوبر جروب"

            await db_register_hidden_owner_group(chat.id, added_by_id)
            logger.info(f"🔒 تم تسجيل المضيف {added_by_id} كمالك مخفي للمجموعة {chat.id}")

            await db_sync_group_admins(chat.id, context.bot, added_by_id)

            owner_info = await detect_owner_type(context.bot, chat.id)
            if owner_info.get('user_id') and owner_info['user_id'] != added_by_id:
                await db_register_hidden_owner_group(chat.id, owner_info['user_id'])
                logger.info(f"👑 تم تسجيل المالك الحقيقي {owner_info['user_id']} أيضاً كمالك مخفي للمجموعة {chat.id}")

            await send_addition_report(context.bot, inviter, chat, chat_type_name)

            try:
                msg = "✅ **تم تفعيل البوت في المجموعة**\n🔒 **تم تسجيلك كمالك مخفي تلقائياً**\n\n📌 استخدم /panel للوحة التحكم"
                await safe_send_markdown(context.bot, chat.id, msg)
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
            if chat.type == 'channel':
                await db_register_channel(chat.id, chat.title or "بدون اسم", adder.id)
                chat_type_name = "قناة"
            elif chat.type in ['group', 'supergroup']:
                await db_register_group(chat.id, chat.title or "بدون اسم", adder.id, chat.username)
                chat_type_name = "مجموعة" if chat.type == 'group' else "سوبر جروب"
                await db_register_hidden_owner_group(chat.id, adder.id)
                await db_sync_group_admins(chat.id, context.bot, adder.id)
            else:
                return
            await send_addition_report(context.bot, adder, chat, chat_type_name)

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
                await safe_send_markdown(context.bot, result.chat.id, msg)
            except:
                pass
    elif result.old_chat_member.status == 'member' and result.new_chat_member.status in ['left', 'kicked']:
        if settings.get('goodbye_enabled'):
            user = result.old_chat_member.user
            msg = settings.get('goodbye_text', "وداعاً {user} 👋")
            msg = msg.replace('{user}', user.full_name or user.first_name).replace('{chat}', result.chat.title)
            try:
                await safe_send_markdown(context.bot, result.chat.id, msg)
            except:
                pass

async def send_addition_report(bot, adder, chat, chat_type_name):
    try:
        if adder:
            await bot.send_message(
                chat_id=adder.id,
                text=f"✅ **تم إضافة البوت إلى {chat_type_name}**\n\n"
                     f"📌 الاسم: {chat.title}\n"
                     f"🆔 المعرف: {chat.id}\n"
                     f"👤 أضيف بواسطة: {adder.full_name or adder.first_name or adder.id}\n\n"
                     f"🔒 **تم تسجيلك كمالك مخفي تلقائياً**\n"
                     f"🔐 استخدم /security لإعدادات الأمان\n"
                     f"🛠️ استخدم /panel للوحة التحكم",
                parse_mode="MarkdownV2"
            )
    except:
        pass

async def detect_owner_type(bot, chat_id):
    try:
        admins = await bot.get_chat_administrators(chat_id)
        for admin in admins:
            if admin.status == 'creator':
                return {'is_hidden': False, 'user_id': admin.user.id}
        return {'is_hidden': True, 'user_id': None}
    except:
        return {'is_hidden': True, 'user_id': None}

# ============================================================
# ===================== إضافة دالة delete_service_messages قبل main() =====================
# ============================================================

async def delete_service_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف رسائل الخدمة (دخول/مغادرة الأعضاء)"""
    if not update.message or not update.effective_chat:
        return
    if not update.message.service_message:
        return
    chat_id = update.effective_chat.id
    try:
        settings = await db_get_security_settings(chat_id)
        if not settings.get('delete_service', False):
            return
    except:
        return
    try:
        await update.message.delete()
        logger.info(f"🗑️ تم حذف رسالة خدمة في المجموعة {chat_id}")
    except Exception as e:
        logger.debug(f"فشل حذف رسالة خدمة: {e}")

# ============================================================
# ===================== معالج الرسائل الرئيسي =====================
# ============================================================

async def message_handler_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    chat = update.effective_chat
    user = update.effective_user
    uid = user.id if user else 0
    text = update.message.text.strip() if update.message.text else ""
    if user and user.is_bot:
        return

    # ===== التحقق من حجم الملفات =====
    if update.message.photo:
        file = await context.bot.get_file(update.message.photo[-1].file_id)
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ حجم الصورة كبير جداً (الحد الأقصى {MAX_FILE_SIZE//(1024*1024)} ميجابايت)")
            return
    if update.message.video:
        file = await context.bot.get_file(update.message.video.file_id)
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ حجم الفيديو كبير جداً (الحد الأقصى {MAX_FILE_SIZE//(1024*1024)} ميجابايت)")
            return
    if update.message.document:
        file = await context.bot.get_file(update.message.document.file_id)
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ حجم الملف كبير جداً (الحد الأقصى {MAX_FILE_SIZE//(1024*1024)} ميجابايت)")
            return
    if update.message.audio:
        file = await context.bot.get_file(update.message.audio.file_id)
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ حجم الصوت كبير جداً (الحد الأقصى {MAX_FILE_SIZE//(1024*1024)} ميجابايت)")
            return
    if update.message.voice:
        file = await context.bot.get_file(update.message.voice.file_id)
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ حجم الرسالة الصوتية كبير جداً (الحد الأقصى {MAX_FILE_SIZE//(1024*1024)} ميجابايت)")
            return
    if update.message.animation:
        file = await context.bot.get_file(update.message.animation.file_id)
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ حجم المتحركة كبير جداً (الحد الأقصى {MAX_FILE_SIZE//(1024*1024)} ميجابايت)")
            return

    # ===== معالجة إلغاء العملية =====
    if text == "/cancel":
        context.user_data.pop('state', None)
        context.user_data.pop('support_mode', None)
        await update.message.reply_text(get_text(uid, 'cancelled'))
        if chat.type == 'private':
            await main_menu_callback(update, context)
        return

    # ===== معالجة المصادقة الثنائية =====
    if context.user_data.get('waiting_2fa') and text:
        if ENABLE_2FA and ADMIN_2FA_SECRET and PYOTP_AVAILABLE:
            try:
                totp = pyotp.TOTP(ADMIN_2FA_SECRET)
                if totp.verify(text):
                    context.user_data['2fa_verified'] = True
                    context.user_data['2fa_time'] = time_module.time()
                    context.user_data.pop('waiting_2fa', None)
                    await update.message.reply_text("✅ تم التحقق من المصادقة الثنائية!")
                    await sendcode_command_handler(update, context)
                    return
                else:
                    await update.message.reply_text("❌ رمز غير صحيح!")
                    context.user_data.pop('waiting_2fa', None)
                    return
            except:
                await update.message.reply_text("❌ خطأ في التحقق")
                context.user_data.pop('waiting_2fa', None)
                return

    # ===== معالجة الحالات =====
    if await state_dispatcher.handle(update, context):
        return

    state = context.user_data.get('state')

    if state == UserState.ADDING_POSTS:
        session_key = f"session_{uid}"
        if text == "/cancel":
            context.user_data.pop(session_key, None)
            context.user_data.pop(f"session_target_{uid}", None)
            context.user_data.pop('state', None)
            await update.message.reply_text(get_text(uid, 'cancelled'))
            await main_menu_callback(update, context)
            return
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
        context.user_data[session_key].append((text_content, media_type, media_file_id))
        cur = len(context.user_data[session_key])
        target = context.user_data.get(f"session_target_{uid}", 15)
        if cur >= target or cur >= MAX_POSTS_PER_SESSION:
            active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
            if not active:
                await update.message.reply_text(get_text(uid, 'error'))
                context.user_data.pop(session_key, None)
                context.user_data.pop('state', None)
                return
            saved = await db_save_posts(active, context.user_data[session_key])
            context.user_data.pop(session_key, None)
            context.user_data.pop(f"session_target_{uid}", None)
            context.user_data.pop('state', None)
            has_sub = await db_has_active_subscription(uid) or await db_has_used_trial(uid)
            auto_status = await db_auto_status(uid)
            if not has_sub:
                await update.message.reply_text(f"✅ تم حفظ {saved} منشور\n⚠️ النشر التلقائي غير مفعل بسبب عدم وجود اشتراك\nاستخدم /trial للحصول على 30 يوماً مجاناً")
            elif not auto_status:
                await update.message.reply_text(f"✅ تم حفظ {saved} منشور\n⚠️ النشر التلقائي معطل\nفعله من الإعدادات")
            else:
                await update.message.reply_text(f"✅ تم حفظ {saved} منشور\n🔄 سيتم نشرها تلقائياً")
            await main_menu_callback(update, context)
        else:
            await update.message.reply_text(f"📥 {cur}/{target}")
        return

    if state in [UserState.WAITING_CONTEST_TITLE, UserState.WAITING_CONTEST_DESCRIPTION,
                 UserState.WAITING_CONTEST_PRIZE, UserState.WAITING_CONTEST_END_DATE,
                 UserState.WAITING_CONTEST_ANSWER]:
        if await handle_contest_creation_states(update, context, state):
            return

    if state == UserState.WAITING_SENDCODE_PASSWORD:
        await handle_sendcode_confirmation_handler(update, context)
        return

    # ===== WAITING_CHANNEL_ID =====
    if state == UserState.WAITING_CHANNEL_ID:
        context.user_data.pop('state', None)
        channel_id = text.strip()
        if not channel_id.startswith('@') and not channel_id.startswith('-100'):
            await update.message.reply_text("❌ **معرف قناة غير صالح!**\n\nالصيغ المدعومة:\n• `@username` (مثل: @my_channel)\n• `-1001234567890` (المعرف الرقمي)\n\nتأكد من أن البوت مشرف في القناة.", parse_mode="MarkdownV2")
            context.user_data['state'] = UserState.WAITING_CHANNEL_ID
            return
        new_id = await db_add_channel(uid, channel_id, channel_id)
        if new_id:
            context.user_data['active_channel'] = new_id
            await db_set_active_channel(uid, new_id)
            await update.message.reply_text(get_text(uid, 'channel_added').format(channel_id))
        else:
            await update.message.reply_text(get_text(uid, 'channel_exists'))
        kb, title, active = await get_main_keyboard(uid)
        context.user_data['active_channel'] = active
        await safe_send_markdown(context.bot, uid, title, reply_markup=kb)
        return

    # ===== WAITING_INTERVAL_MINUTES =====
    if state == UserState.WAITING_INTERVAL_MINUTES:
        context.user_data.pop('state', None)
        ch_db_id = context.user_data.pop('schedule_ch_id', None)
        is_admin = context.user_data.pop('admin_interval', False)
        is_cron = context.user_data.pop('schedule_cron', False)

        if is_cron:
            cron_expr = text.strip()
            if len(cron_expr.split()) >= 5:
                await schedule_cron(ch_db_id, cron_expr)
                await db_set_next_publish_date(ch_db_id, None)
                await update.message.reply_text(f"✅ **تم حفظ تعبير CRON:** `{cron_expr}`")
                await schedule_menu_callback(update, context)
                return
            else:
                await update.message.reply_text("❌ **تعبير CRON غير صحيح!**\nتأكد من الصيغة: `دقيقة ساعة يوم شهر يوم_أسبوع`")
                return

        try:
            minutes = int(text)
            if minutes < 1:
                minutes = 1
            if is_admin:
                seconds = minutes * 60
                if seconds > 86400:
                    seconds = 86400
                await db_set_publish_interval_seconds(seconds, uid, is_admin=True)
                await update.message.reply_text(f"✅ **تم ضبط وقت النشر العام بنجاح!**\n\n🕐 الوقت الجديد: {minutes} دقيقة ({seconds} ثانية)")
                await admin_panel_callback(update, context)
            else:
                await db_save_schedule(ch_db_id, 'interval_minutes', interval_minutes=minutes)
                await db_set_next_publish_date(ch_db_id, None)
                await update.message.reply_text(get_text(uid, 'interval_set'))
                await schedule_menu_callback(update, context)
        except ValueError:
            await update.message.reply_text(get_text(uid, 'invalid_number'))
        return

    # ===== WAITING_INTERVAL_HOURS =====
    if state == UserState.WAITING_INTERVAL_HOURS:
        context.user_data.pop('state', None)
        ch_db_id = context.user_data.pop('schedule_ch_id', None)
        try:
            hours = int(text)
            if hours < 1:
                hours = 1
            await db_save_schedule(ch_db_id, 'interval_hours', interval_hours=hours)
            await db_set_next_publish_date(ch_db_id, None)
            await update.message.reply_text(get_text(uid, 'interval_set'))
        except:
            await update.message.reply_text(get_text(uid, 'invalid_number'))
        await schedule_menu_callback(update, context)
        return

    # ===== WAITING_INTERVAL_DAYS =====
    if state == UserState.WAITING_INTERVAL_DAYS:
        context.user_data.pop('state', None)
        ch_db_id = context.user_data.pop('schedule_ch_id', None)
        try:
            days = int(text)
            if days < 1:
                days = 1
            await db_save_schedule(ch_db_id, 'interval_days', interval_days=days)
            await db_set_next_publish_date(ch_db_id, None)
            await update.message.reply_text(get_text(uid, 'interval_set'))
        except:
            await update.message.reply_text(get_text(uid, 'invalid_number'))
        await schedule_menu_callback(update, context)
        return

    # ===== WAITING_DATES =====
    if state == UserState.WAITING_DATES:
        context.user_data.pop('state', None)
        ch_db_id = context.user_data.pop('schedule_ch_id', None)
        dates = text.split(',')
        valid_dates = []
        for d in dates:
            d = d.strip()
            try:
                datetime.strptime(d, '%Y-%m-%d')
                valid_dates.append(d)
            except:
                await update.message.reply_text(get_text(uid, 'invalid_date'))
                return
        await db_save_schedule(ch_db_id, 'dates', specific_dates=json.dumps(valid_dates))
        await db_set_next_publish_date(ch_db_id, None)
        await update.message.reply_text(get_text(uid, 'dates_saved'))
        await schedule_menu_callback(update, context)
        return

    # ===== WAITING_PUBLISH_TIME =====
    if state == UserState.WAITING_PUBLISH_TIME:
        context.user_data.pop('state', None)
        ch_db_id = context.user_data.pop('schedule_ch_id', None)
        try:
            time_str = text.strip()
            hour, minute = map(int, time_str.split(':'))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                await db_set_publish_time(ch_db_id, time_str)
                await db_set_next_publish_date(ch_db_id, None)
                await update.message.reply_text(get_text(uid, 'interval_set'))
            else:
                await update.message.reply_text(get_text(uid, 'invalid_time'))
        except:
            await update.message.reply_text(get_text(uid, 'invalid_time'))
        await schedule_menu_callback(update, context)
        return

    # ===== WAITING_SCHEDULE_POST =====
    if state == UserState.WAITING_SCHEDULE_POST:
        context.user_data.pop('state', None)
        args = text.split()
        if len(args) < 3:
            await update.message.reply_text("❌ **صيغة غير صحيحة!**\n\nالاستخدام الصحيح:\n`YYYY-MM-DD HH:MM نص المنشور`\n\nمثال: `2024-12-31 20:00 مرحباً بالجميع!`", parse_mode="MarkdownV2")
            return
        try:
            date_str = args[0]
            time_str = args[1]
            post_text = " ".join(args[2:])
            mecca_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            if mecca_dt <= mecca_now():
                await update.message.reply_text("❌ **الوقت يجب أن يكون في المستقبل!**", parse_mode="MarkdownV2")
                return
            utc_dt = mecca_to_utc(mecca_dt)
            await db_add_scheduled_post(chat.id, post_text, utc_dt)
            await update.message.reply_text(f"✅ **تم جدولة المنشور بنجاح!**\n\n📅 التاريخ: {date_str}\n🕐 الوقت: {time_str} (بتوقيت مكة)\n📝 المنشور: {post_text[:100]}{'...' if len(post_text) > 100 else ''}", parse_mode="MarkdownV2")
        except ValueError:
            await update.message.reply_text("❌ **صيغة التاريخ أو الوقت غير صحيحة!**\n\nتأكد من الصيغة:\n• التاريخ: YYYY-MM-DD (مثال: 2024-12-31)\n• الوقت: HH:MM (مثال: 20:00)", parse_mode="MarkdownV2")
        await main_menu_callback(update, context)
        return

    # ===== WAITING_REMINDER_DAYS =====
    if state == UserState.WAITING_REMINDER_DAYS:
        context.user_data.pop('state', None)
        try:
            days = int(text)
            if 1 <= days <= 10:
                await db_update_reminder_settings(uid, reminder_days_before=days)
                await update.message.reply_text(f"✅ تم تعيين التذكير قبل {days} يوم من انتهاء الاشتراك")
            else:
                await update.message.reply_text("❌ الرجاء إدخال رقم بين 1 و 10")
        except ValueError:
            await update.message.reply_text("❌ الرجاء إدخال رقم صحيح")
        await reminder_menu_callback(update, context)
        return

    # ===== WAITING_UPDATE_TEXT =====
    if state == UserState.WAITING_UPDATE_TEXT:
        context.user_data.pop('state', None)
        channel = await db_get_updates_channel()
        if channel:
            try:
                await context.bot.send_message(chat_id=f"@{channel}", text=text, parse_mode="HTML")
                await update.message.reply_text("✅ تم نشر التحديث في قناة التحديثات")
            except Exception as e:
                await update.message.reply_text(f"❌ فشل النشر: {str(e)[:100]}\nتأكد من أن البوت مشرف في القناة @{channel}")
        else:
            await update.message.reply_text("❌ لم يتم تعيين قناة تحديثات بعد\nاستخدم زر '⚙️ قناة التحديثات' أولاً")
        await admin_panel_callback(update, context)
        return

    # ===== WAITING_UPDATE_CHANNEL =====
    if state == UserState.WAITING_UPDATE_CHANNEL:
        context.user_data.pop('state', None)
        channel = text.strip()
        if channel.startswith('@'):
            channel = channel[1:]
        if not channel:
            await update.message.reply_text("❌ **معرف قناة غير صالح!**\nالرجاء إدخال معرف صحيح.")
            return
        try:
            if channel.startswith('-'):
                chat_obj = await context.bot.get_chat(int(channel))
            else:
                chat_obj = await context.bot.get_chat(f"@{channel}")
            if chat_obj.type != 'channel':
                await update.message.reply_text("❌ **هذا ليس قناة!**\nتأكد من أن المعرف ينتمي لقناة.")
                return
            success = await db_set_updates_channel(channel)
            if success:
                saved_channel = await db_get_updates_channel()
                if saved_channel == channel:
                    await update.message.reply_text(f"✅ **تم تعيين قناة التحديثات بنجاح!**\n📢 القناة: @{channel}")
                    try:
                        await context.bot.send_message(
                            chat_id=f"@{channel}",
                            text="✅ **تم تفعيل قناة التحديثات!**\nسيتم نشر التحديثات هنا."
                        )
                        await update.message.reply_text("✅ تم إرسال رسالة اختبار للقناة.")
                    except Exception as e:
                        await update.message.reply_text(f"⚠️ **تنبيه:** لم أتمكن من إرسال رسالة اختبار للقناة.\nتأكد من أن البوت مشرف ولديه صلاحية الإرسال.\nالخطأ: {str(e)[:100]}")
                else:
                    await update.message.reply_text("❌ **فشل حفظ القناة!** حاول مرة أخرى.")
            else:
                await update.message.reply_text("❌ **فشل حفظ القناة!** المعرف غير صالح.")
        except Exception as e:
            await update.message.reply_text(f"❌ **لا يمكن الوصول إلى القناة:**\n{str(e)[:200]}\n\n📌 تأكد من:\n• المعرف صحيح\n• البوت مشرف في القناة\n• القناة عامة (Public)")
        await admin_panel_callback(update, context)
        return

    # ===== WAITING_FORCE_CHANNEL =====
    if state == UserState.WAITING_FORCE_CHANNEL:
        context.user_data.pop('state', None)
        await db_set_force_subscribe_channel(text)
        await update.message.reply_text(f"✅ تم تعيين قناة الاشتراك الإجباري: {text}")
        await admin_panel_callback(update, context)
        return

    # ===== WAITING_BROADCAST =====
    if state == UserState.WAITING_BROADCAST:
        context.user_data.pop('state', None)
        confirm_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ نعم، أرسل", callback_data=CallbackData.ADMIN_CONFIRM_BROADCAST),
             InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.ADMIN_PANEL)]
        ])
        context.user_data['broadcast_text'] = text
        await update.message.reply_text(f"📨 **تأكيد الإرسال الجماعي**\n\nالنص المرسل:\n━━━━━━━━━━━━━━\n{text[:500]}\n━━━━━━━━━━━━━━\n\n⚠️ سيتم إرسال هذه الرسالة إلى **جميع مستخدمي البوت**\nهل أنت متأكد؟", reply_markup=confirm_kb, parse_mode="MarkdownV2")
        return

    # ===== WAITING_SENDCODE_USER =====
    if state == UserState.WAITING_SENDCODE_USER:
        context.user_data.pop('state', None)
        try:
            target_user_id = int(text)
        except ValueError:
            await update.message.reply_text(get_text(uid, 'invalid_number'))
            return
        await db_set_allowed_sendcode_user(target_user_id)
        await security_audit.log("SENDCODE_PERMISSION_GRANTED", uid, {"target": target_user_id}, "CRITICAL")
        await update.message.reply_text(f"✅ تم منح صلاحية /sendcode للمستخدم `{target_user_id}`")
        await admin_panel_callback(update, context)
        return

    # ===== WAITING_LOG_CHANNEL =====
    if state == UserState.WAITING_LOG_CHANNEL:
        context.user_data.pop('state', None)
        identifier = text.strip()
        if not identifier.startswith('@') and not identifier.startswith('-100'):
            await update.message.reply_text("❌ **معرف قناة غير صالح!**\n\nالصيغ المدعومة:\n• `@username` (مثل: @my_channel)\n• `-1001234567890` (المعرف الرقمي)", parse_mode="MarkdownV2")
            context.user_data['state'] = UserState.WAITING_LOG_CHANNEL
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
                await update.message.reply_text("❌ **البوت ليس مشرفاً في هذه القناة.**", parse_mode="MarkdownV2")
                context.user_data['state'] = UserState.WAITING_LOG_CHANNEL
                return
            if not bot_member.can_post_messages:
                await update.message.reply_text("❌ **البوت لا يملك صلاحية الإرسال في هذه القناة.**", parse_mode="MarkdownV2")
                context.user_data['state'] = UserState.WAITING_LOG_CHANNEL
                return
            await db_set_log_channel_id(str(chat_id))
            await update.message.reply_text(f"✅ **تم تعيين قناة التقارير بنجاح!**\nمعرف القناة: `{chat_id}`", parse_mode="MarkdownV2")
            try:
                await context.bot.send_message(chat_id, "✅ **تم تفعيل نظام التقارير**")
            except:
                pass
        except Exception as e:
            await update.message.reply_text(f"❌ **لا يمكن الوصول إلى القناة:**\n{str(e)[:200]}", parse_mode="MarkdownV2")
            context.user_data['state'] = UserState.WAITING_LOG_CHANNEL
            return
        await admin_panel_callback(update, context)
        return

    # ===== WAITING_KEYWORD =====
    if state == UserState.WAITING_KEYWORD:
        context.user_data.pop('state', None)
        keyword = text.strip().lower()
        if len(keyword) < 2:
            await update.message.reply_text("❌ الكلمة المفتاحية قصيرة جداً (يجب أن تكون حرفين على الأقل)")
            context.user_data['state'] = UserState.WAITING_KEYWORD
            return
        context.user_data['state'] = UserState.WAITING_REPLY
        context.user_data['admin_keyword'] = keyword
        await update.message.reply_text(f"📝 **إضافة رد للكلمة:** `{keyword}`\n\nأرسل الرد الذي تريده لهذه الكلمة:", parse_mode="MarkdownV2")
        return

    # ===== WAITING_REPLY =====
    if state == UserState.WAITING_REPLY:
        context.user_data.pop('state', None)
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
        await admin_replies_callback(update, context)
        return

    # ===== WAITING_ADMIN_ID_ADD =====
    if state == UserState.WAITING_ADMIN_ID_ADD:
        try:
            target_id = int(text)
            if target_id == PRIMARY_OWNER_ID:
                await update.message.reply_text(get_text(uid, 'cannot_remove_main_admin'))
            else:
                await add_bot_admin(target_id)
                await security_audit.log("ADMIN_ADDED", uid, {"target": target_id}, "CRITICAL")
                await update.message.reply_text(f"✅ تم إضافة المستخدم `{target_id}` كمشرف")
        except ValueError:
            await update.message.reply_text(get_text(uid, 'invalid_user_id'))
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return

    # ===== WAITING_ADMIN_ID_REMOVE =====
    if state == UserState.WAITING_ADMIN_ID_REMOVE:
        try:
            target_id = int(text)
            if target_id == PRIMARY_OWNER_ID:
                await update.message.reply_text(get_text(uid, 'cannot_remove_main_admin'))
            else:
                await remove_bot_admin(target_id)
                await security_audit.log("ADMIN_REMOVED", uid, {"target": target_id}, "CRITICAL")
                await update.message.reply_text(f"✅ تم إزالة المستخدم `{target_id}` من المشرفين")
        except ValueError:
            await update.message.reply_text(get_text(uid, 'invalid_user_id'))
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return

    # ===== WAITING_GROUP_BANNED_WORD =====
    if state == UserState.WAITING_GROUP_BANNED_WORD:
        chat_id = context.user_data.get('banned_words_chat_id')
        if chat_id:
            word = text.split()[0].lower() if text else ""
            if len(word) < 2:
                await update.message.reply_text("❌ الكلمة قصيرة جداً")
                return
            if await db_add_banned_word(word, chat_id, uid):
                await update.message.reply_text(f"✅ تم إضافة {word}")
            else:
                await update.message.reply_text(f"⚠️ {word} موجودة مسبقاً")
            context.user_data.pop('state', None)
            await banned_words_list_callback(update, context)
        return

    # ===== WAITING_REMOVE_GROUP_BANNED_WORD =====
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

    # ===== WAITING_GLOBAL_BANNED_WORD =====
    if state == UserState.WAITING_GLOBAL_BANNED_WORD:
        word = text.split()[0].lower() if text else ""
        if len(word) < 2:
            await update.message.reply_text("❌ الكلمة قصيرة جداً")
            return
        if await db_add_banned_word(word, -1, uid):
            await update.message.reply_text(f"✅ تم إضافة {word} ككلمة محظورة عامة")
        else:
            await update.message.reply_text(f"⚠️ {word} موجودة مسبقاً")
        context.user_data.pop('state', None)
        await admin_banned_words_callback(update, context)
        return

    # ===== WAITING_REMOVE_GLOBAL_BANNED_WORD =====
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

    # ===== WAITING_NSFW_THRESHOLD =====
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

    # ===== معالجة الأوامر المتقدمة =====
    if state and isinstance(state, UserState) and state.name.startswith('WAITING_'):
        chat_id = context.user_data.get('advanced_chat_id')
        if not chat_id:
            return

        if state == UserState.WAITING_BAN_USER:
            parts = text.split(maxsplit=1)
            reason = parts[1] if len(parts) > 1 else ""
            try:
                target_id = int(parts[0])
                success, msg = await execute_ban(context.bot, chat_id, target_id, reason=reason, moderator_id=uid)
                await safe_send_markdown(context.bot, chat_id, msg)
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
                success, msg = await execute_mute(context.bot, chat_id, target_id, minutes, reason=reason, moderator_id=uid)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
            context.user_data.pop('state', None)
            return

        if state == UserState.WAITING_WARN_USER:
            parts = text.split(maxsplit=1)
            reason = parts[1] if len(parts) > 1 else ""
            try:
                target_id = int(parts[0])
                success, msg = await execute_warn(context.bot, chat_id, target_id, uid, reason=reason)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
            context.user_data.pop('state', None)
            return

        if state == UserState.WAITING_KICK_USER:
            parts = text.split(maxsplit=1)
            reason = parts[1] if len(parts) > 1 else ""
            try:
                target_id = int(parts[0])
                success, msg = await execute_kick(context.bot, chat_id, target_id, reason=reason, moderator_id=uid)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
            context.user_data.pop('state', None)
            return

        if state == UserState.WAITING_RESTRICT_USER:
            parts = text.split(maxsplit=1)
            reason = parts[1] if len(parts) > 1 else ""
            try:
                target_id = int(parts[0])
                success, msg = await execute_restrict(context.bot, chat_id, target_id, reason=reason, moderator_id=uid)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
            context.user_data.pop('state', None)
            return

        if state == UserState.WAITING_UNBAN_USER:
            try:
                target_id = int(text)
                success, msg = await execute_unban(context.bot, chat_id, target_id, moderator_id=uid)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
            context.user_data.pop('state', None)
            return

        if state == UserState.WAITING_PIN_MESSAGE:
            if update.message.reply_to_message:
                success, msg = await execute_pin(context.bot, chat_id, update.message.reply_to_message.message_id)
                await safe_send_markdown(context.bot, chat_id, msg)
            else:
                await update.message.reply_text("❌ يرجى الرد على الرسالة التي تريد تثبيتها")
            context.user_data.pop('state', None)
            return

    # ===== وضع الدعم =====
    if context.user_data.get('support_mode') and chat.type == 'private' and text and not text.startswith('/'):
        ticket_num = await db_get_next_ticket_number()
        username = user.full_name or user.first_name or str(uid)
        clean_text = sanitize_text(text, max_length=2000)
        await db_save_ticket(uid, username, clean_text, ticket_num)
        now_mecca = mecca_now()
        now_str = now_mecca.strftime("%Y-%m-%d %H:%M:%S")
        reply_text = f"✅ **تم استلام رسالتك!**\n📋 رقم التذكرة: #{ticket_num}\n🕐 {now_str}\n\nسيتم الرد عليك في أقرب وقت ممكن."
        await update.message.reply_text(reply_text, parse_mode="MarkdownV2")
        notification_text = f"📬 **تذكرة دعم جديدة**\n━━━━━━━━━━━━━━━━━━━━━━\n👤 المستخدم: {username}\n🆔 المعرف: `{uid}`\n📋 رقم التذكرة: #{ticket_num}\n🕐 الوقت: {now_str}\n━━━━━━━━━━━━━━━━━━━━━━\n📝 **الرسالة:**\n{clean_text[:500]}\n━━━━━━━━━━━━━━━━━━━━━━\nللرد استخدم:\n`/support_reply {uid} نص الرد`"
        await context.bot.send_message(chat_id=PRIMARY_OWNER_ID, text=notification_text, parse_mode="MarkdownV2")
        context.user_data['support_mode'] = False
        return

    # ===== أوامر الخاصة =====
    if chat.type == 'private':
        if text == "/start":
            await start_command_handler(update, context)
        elif text == "/cancel":
            context.user_data.pop('state', None)
            await update.message.reply_text(get_text(uid, 'cancelled'))
            await main_menu_callback(update, context)

# ===================== معالج الأخطاء العالمي =====================
async def global_error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        error = context.error
        error_id = advanced_logger.log_error("خطأ في تحديث", error, {
            'user_id': update.effective_user.id if update and update.effective_user else None,
            'chat_id': update.effective_chat.id if update and update.effective_chat else None,
            'message': update.effective_message.text if update and update.effective_message else None
        })

        if isinstance(error, Conflict):
            logger.warning(f"⚠️ تعارض في التحديثات (Conflict): {error}")
            return

        if isinstance(error, Forbidden):
            logger.warning(f"⚠️ البوت محظور أو ليس لديه صلاحيات: {error}")
            if update and update.effective_chat:
                try:
                    await context.bot.send_message(
                        chat_id=PRIMARY_OWNER_ID,
                        text=f"⚠️ **البوت محظور أو ليس لديه صلاحيات في:**\n{update.effective_chat.title}\nID: `{update.effective_chat.id}`"
                    )
                except:
                    pass
            return

        if isinstance(error, TimedOut):
            logger.warning(f"⏱️ انتهت المهلة: {error}")
            return

        if update and update.effective_user and context and context.bot:
            try:
                await safe_send_markdown(
                    context.bot,
                    update.effective_user.id,
                    f"❌ حدث خطأ:\n`{str(error)[:300]}`\n(الرمز: `{error_id}`)"
                )
            except Exception as e:
                logger.error(f"فشل إرسال رسالة الخطأ للمستخدم: {e}")
                try:
                    await context.bot.send_message(
                        chat_id=update.effective_user.id,
                        text=f"❌ خطأ: `{str(error)[:300]}` (كود: {error_id})"
                    )
                except:
                    pass

        if PRIMARY_OWNER_ID and context and context.bot:
            try:
                error_text = f"🚨 **خطأ في البوت** (الرمز: {error_id})\n\n"
                error_text += f"📌 المستخدم: {update.effective_user.id if update and update.effective_user else 'غير معروف'}\n"
                error_text += f"⚠️ الخطأ: `{str(error)[:300]}`\n"
                if update and update.effective_message and update.effective_message.text:
                    error_text += f"📝 الرسالة: `{update.effective_message.text[:100]}`\n"
                await context.bot.send_message(PRIMARY_OWNER_ID, error_text, parse_mode="MarkdownV2")
            except Exception as e:
                logger.error(f"فشل إرسال إشعار الخطأ للمطور: {e}")
    except Exception as e:
        logger.error(f"فشل معالج الأخطاء نفسه: {e}")

# ===================== فلتر الرسائل مع كشف NSFW =====================
async def filter_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    chat = update.effective_chat
    user = update.effective_user
    chat_id = chat.id
    user_id = user.id
    if chat.type not in ['group', 'supergroup']:
        return
    if user.is_bot:
        return

    # ===== التحقق من قفل المجموعة =====
    if await is_chat_locked(chat_id):
        try:
            await update.message.delete()
            await safe_send_markdown(context.bot, chat_id, f"🔒 المجموعة مقفلة من قبل المشرف", 5)
        except:
            pass
        return

    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        return

    # ===== التحقق من الوضع البطيء =====
    if not await db_check_slow_mode(chat_id, user_id):
        try:
            await update.message.delete()
            await safe_send_markdown(context.bot, chat_id, f"⏱️ **وضع بطيء مفعل**\n@{user.username or str(user_id)} يرجى الانتظار قبل إرسال رسالة جديدة", 3)
        except:
            pass
        return

    # ===================== كشف NSFW =====================
    if NSFW_ENABLED:
        # كشف الصور
        if update.message.photo:
            file = await context.bot.get_file(update.message.photo[-1].file_id)
            if file.file_size > NSFW_MAX_FILE_SIZE:
                await update.message.reply_text(f"⚠️ حجم الصورة كبير جداً للتحليل (الحد الأقصى {NSFW_MAX_FILE_SIZE // (1024*1024)} ميجابايت)")
                return

            try:
                file_bytes = await file.download_as_bytearray()
                cache_key = hashlib.md5(file_bytes).hexdigest()
                result = await check_nsfw_cached(file_bytes, cache_key)

                if result.get("error"):
                    logger.warning(f"خطأ في كشف NSFW: {result.get('error')}")
                elif result.get("nsfw", False):
                    await update.message.delete()
                    warning = f"🚫 **تم حذف الصورة**\n\nنسبة المحتوى غير اللائق: {result['nsfw_score'] * 100:.0f}%\n@{user.username or str(user_id)} يرجى احترام قوانين المجموعة."
                    await safe_send_markdown(context.bot, chat_id, warning)
                    security_settings = await db_get_security_settings(chat_id)
                    await apply_penalty(context.bot, chat_id, user_id, security_settings)
                    return
            except Exception as e:
                logger.error(f"خطأ في تحليل الصورة NSFW: {e}")

        # كشف الفيديوهات
        elif update.message.video:
            if not CV2_AVAILABLE:
                logger.warning("cv2 غير مثبت، تخطي كشف NSFW للفيديو")
                return

            file = await context.bot.get_file(update.message.video.file_id)
            if file.file_size > NSFW_MAX_VIDEO_SIZE:
                await update.message.reply_text(f"⚠️ حجم الفيديو كبير جداً للتحليل (الحد الأقصى {NSFW_MAX_VIDEO_SIZE // (1024*1024)} ميجابايت)")
                return

            try:
                file_bytes = await file.download_as_bytearray()
                result = await check_nsfw_video(file_bytes, frames=NSFW_FRAMES)

                if result.get("error"):
                    logger.warning(f"خطأ في كشف NSFW للفيديو: {result.get('error')}")
                elif result.get("nsfw", False):
                    await update.message.delete()
                    warning = f"🚫 **تم حذف الفيديو**\n\nنسبة المحتوى غير اللائق: {result['nsfw_score'] * 100:.0f}%\nتم تحليل {result.get('frames_analyzed', 0)} إطار.\n@{user.username or str(user_id)} يرجى احترام قوانين المجموعة."
                    await safe_send_markdown(context.bot, chat_id, warning)
                    security_settings = await db_get_security_settings(chat_id)
                    await apply_penalty(context.bot, chat_id, user_id, security_settings)
                    return
            except Exception as e:
                logger.error(f"خطأ في تحليل الفيديو NSFW: {e}")

    # ===================== الردود التلقائية =====================

    # 1. التحقق من إعدادات المستخدم
    user_reply_enabled = await db_get_user_auto_reply_status(user_id)
    if not user_reply_enabled:
        return

    # 2. التحقق من إعدادات المجموعة
    settings = await db_get_auto_reply_settings(chat_id)
    if not settings['enabled']:
        return

    # 3. التحقق من صلاحيات المستخدم (إذا كان المشرفين فقط)
    if settings['only_admins']:
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            return

    # 4. تجاهل البوتات
    if settings['ignore_bots'] and update.effective_user.is_bot:
        return

    # 5. التحقق من إعدادات الأمان
    security_settings = await db_get_security_settings(chat_id)

    text = update.message.text or update.message.caption or ""

    # ===== حذف الفيديوهات =====
    if security_settings.get('delete_videos') and update.message.video:
        try:
            await update.message.delete()
            await safe_send_markdown(context.bot, chat_id, f"🎬 **الفيديوهات غير مسموح بها**\n@{user.username or str(user_id)}")
        except:
            pass
        await apply_penalty(context.bot, chat_id, user_id, security_settings)
        return

    # ===== حذف رسائل الخدمة =====
    if security_settings.get('delete_service') and update.message.service_message:
        try:
            await update.message.delete()
        except:
            pass
        return

    # ===== حذف الملفات =====
    if security_settings.get('delete_documents') and update.message.document:
        try:
            await update.message.delete()
            await safe_send_markdown(context.bot, chat_id, f"📄 **الملفات غير مسموح بها**\n@{user.username or str(user_id)}")
        except:
            pass
        await apply_penalty(context.bot, chat_id, user_id, security_settings)
        return

    # ===== حذف الملصقات =====
    if security_settings.get('delete_stickers') and update.message.sticker:
        try:
            await update.message.delete()
            await safe_send_markdown(context.bot, chat_id, f"🖼️ **الملصقات غير مسموح بها**\n@{user.username or str(user_id)}")
        except:
            pass
        await apply_penalty(context.bot, chat_id, user_id, security_settings)
        return

    # ===== حذف الكلمات المحظورة =====
    if security_settings.get('delete_banned_words'):
        banned_word = await db_contains_banned_word(text, chat_id)
        if banned_word:
            try:
                await update.message.delete()
                await safe_send_markdown(context.bot, chat_id, f"🚫 **كلمة محظورة**\n@{user.username or str(user_id)} الكلمة `{banned_word}` غير مسموح بها")
            except:
                pass
            await apply_penalty(context.bot, chat_id, user_id, security_settings)
            return

    # ===== حذف الروابط =====
    if security_settings.get('links') and contains_link(text):
        try:
            await update.message.delete()
            await safe_send_markdown(context.bot, chat_id, f"🔗 **الروابط غير مسموح بها**\n@{user.username or str(user_id)}")
        except:
            pass
        await apply_penalty(context.bot, chat_id, user_id, security_settings)
        return

    # ===== حذف المعرفات =====
    if security_settings.get('mentions') and contains_mention(text):
        try:
            await update.message.delete()
            await safe_send_markdown(context.bot, chat_id, f"@ **المعرفات غير مسموح بها**\n@{user.username or str(user_id)}")
        except:
            pass
        await apply_penalty(context.bot, chat_id, user_id, security_settings)
        return

    # ===== البحث عن الرد مع المطابقة الجزئية =====
    reply = None
    text_lower = text.lower()

    # المستوى 1: ردود مخصصة (قاعدة البيانات) - بحث مباشر
    if text_lower:
        reply = await db_get_reply(text_lower)

    # المستوى 2: ردود مضمنة (مطابقة تامة)
    if not reply and text_lower in ALL_REPLIES:
        reply = ALL_REPLIES[text_lower]

    # المستوى 3: ردود مضمنة (مطابقة جزئية)
    if not reply:
        for keyword, response in ALL_REPLIES.items():
            if keyword in text_lower:
                reply = response
                break

    # إرسال الرد
    if reply:
        try:
            await update.message.reply_text(reply)
        except Exception as e:
            logger.error(f"فشل إرسال الرد: {e}")

    # ===================== رسالة ترويجية للعضو العادي =====================
    if text.startswith('/') and not await is_authorized_in_group(context.bot, chat_id, user_id):
        promo_msg = get_text(user_id, 'promo_message').format(BOT_USERNAME)
        try:
            await update.message.reply_text(promo_msg, parse_mode="MarkdownV2")
        except Exception as e:
            logger.error(f"فشل إرسال رسالة ترويجية: {e}")

# ===================== خادم الويب =====================
web_app = web.Application()

async def health_check_handler(request):
    try:
        db_healthy = await check_database_health()
        tg_healthy = await check_telegram_health()
        ram = get_ram_usage()
        checks = {
            'database': db_healthy,
            'telegram_api': tg_healthy,
            'memory': ram,
            'uptime': time_module.time() - getattr(health_check_handler, 'start_time', time_module.time())
        }
        status = 200 if all([checks['database'], checks['telegram_api']]) else 503
        return web.json_response({
            'status': 'healthy' if status == 200 else 'unhealthy',
            'checks': checks
        }, status=status)
    except Exception as e:
        return web.json_response({
            'status': 'unhealthy',
            'error': str(e)
        }, status=503)

web_app.router.add_get('/health', health_check_handler)

# ===================== نظام إدارة المهام =====================
class TaskManager:
    def __init__(self, max_tasks=50, max_concurrent=10):
        self.tasks = set()
        self._lock = asyncio.Lock()
        self.max_tasks = max_tasks
        self.semaphore = asyncio.Semaphore(max_concurrent)

    def create_task(self, coro: Awaitable) -> asyncio.Task:
        async def _wrapped():
            async with self.semaphore:
                return await coro

        if len(self.tasks) >= self.max_tasks:
            try:
                oldest = next(iter(self.tasks))
                oldest.cancel()
            except StopIteration:
                pass

        task = asyncio.create_task(_wrapped())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def cancel_all(self):
        for task in list(self.tasks):
            if not task.done():
                task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

task_manager = TaskManager(max_concurrent=10)

# ===================== أنظمة التشغيل الخلفي =====================
async def auto_publish_loop_improved(bot):
    await asyncio.sleep(5)
    consecutive_errors = 0
    backoff = 10
    max_backoff = 60

    semaphore = asyncio.Semaphore(5)

    async def publish_one(row):
        async with semaphore:
            ch_db_id, ch_tele_id, user_id = row
            if not await db_has_active_subscription(user_id) and not await db_has_used_trial(user_id):
                return
            has_permission, permission_msg = await check_bot_permissions(bot, ch_tele_id)
            if not has_permission:
                return

            auto_recycle = await db_get_auto_recycle(user_id)

            total = await db_get_posts_count(ch_db_id)
            published = await db_get_published_count(ch_db_id)

            if total > 0 and published >= total:
                if auto_recycle:
                    logger.info(f"♻️ إعادة تدوير تلقائي للقناة {ch_tele_id} (مفعلة للمستخدم {user_id})")
                    await db_reset_all_posts_to_unpublished(ch_db_id)
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text=f"♻️ **تم إعادة تدوير المنشورات تلقائياً!**\n\n📡 القناة: {ch_tele_id}\n📝 تم إعادة تعيين {total} منشور للنشر من جديد.",
                            parse_mode="MarkdownV2"
                        )
                    except:
                        pass
                    return
                else:
                    logger.warning(f"⛔ توقف النشر للقناة {ch_tele_id} (auto_recycle معطل للمستخدم {user_id})")
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text=f"⚠️ **توقف النشر التلقائي**\n\n📡 القناة: {ch_tele_id}\n📝 تم نشر جميع المنشورات ({published}/{total}).\n\n♻️ إعادة التدوير التلقائي معطل.\n📌 قم بتفعيله من الإعدادات أو أضف منشورات جديدة.",
                            parse_mode="MarkdownV2"
                        )
                    except:
                        pass
                    await db_set_next_publish_date(ch_db_id, utc_now() + timedelta(days=365))
                    return

            post = await db_get_next_post(ch_db_id)
            if not post:
                if auto_recycle:
                    total = await db_get_posts_count(ch_db_id)
                    if total > 0:
                        await db_reset_all_posts_to_unpublished(ch_db_id)
                        logger.info(f"♻️ إعادة تدوير تلقائي للقناة {ch_tele_id} (لا توجد منشورات غير منشورة)")
                        try:
                            await bot.send_message(
                                chat_id=user_id,
                                text=f"♻️ **تم إعادة تدوير المنشورات تلقائياً!**\n\n📡 القناة: {ch_tele_id}\n📝 تم إعادة تعيين {total} منشور للنشر من جديد.",
                                parse_mode="MarkdownV2"
                            )
                        except:
                            pass
                        return
                    else:
                        logger.info(f"📭 لا توجد منشورات في القناة {ch_tele_id}")
                        return
                else:
                    logger.info(f"📭 لا توجد منشورات للقناة {ch_tele_id} (auto_recycle معطل)")
                    return

            translation_lang = await get_user_translation_language(user_id)
            final_text = post['text']
            if translation_lang != 'off' and final_text:
                try:
                    translated = await translate_text(final_text, translation_lang)
                    if translated and translated != final_text:
                        final_text = f"{final_text}\n\n🌐 {translated}"
                except:
                    pass
            success = False
            for attempt in range(3):
                try:
                    if post['media_type'] == 'photo' and post['media_file_id']:
                        await bot.send_photo(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
                    elif post['media_type'] == 'video' and post['media_file_id']:
                        await bot.send_video(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
                    elif post['media_type'] == 'document' and post['media_file_id']:
                        await bot.send_document(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
                    elif post['media_type'] == 'audio' and post['media_file_id']:
                        await bot.send_audio(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
                    elif post['media_type'] == 'voice' and post['media_file_id']:
                        await bot.send_voice(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
                    elif post['media_type'] == 'animation' and post['media_file_id']:
                        await bot.send_animation(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
                    else:
                        await bot.send_message(ch_tele_id, final_text, parse_mode=None)
                    success = True
                    break
                except Exception as e:
                    logger.warning(f"محاولة {attempt+1} فشلت في النشر للقناة {ch_tele_id}: {e}")
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
            if success:
                await db_mark_published(post['id'])
                await db_set_last_publish(ch_db_id, utc_now())
                await db_update_next_publish_date(ch_db_id)
            else:
                await db_increment_fail_count(post['id'])
                logger.error(f"فشل دائم في نشر المنشور {post['id']} في القناة {ch_tele_id}")
                next_retry = utc_now() + timedelta(seconds=PUBLISH_RETRY_DELAY)
                await db_set_next_publish_date(ch_db_id, next_retry)
            await asyncio.sleep(random.uniform(2, 5))

    while True:
        try:
            publish_interval = await db_get_publish_interval_seconds()
            async def _get_due_channels(conn, limit=MAX_CHANNELS_PER_CYCLE):
                now_utc_iso = utc_now().isoformat()
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
                    LIMIT ?
                """, (now_utc_iso, limit))
                return await cur.fetchall()
            rows = await execute_db(_get_due_channels)

            tasks = [publish_one(row) for row in rows]
            await asyncio.gather(*tasks, return_exceptions=True)

            consecutive_errors = 0
            backoff = publish_interval
            await asyncio.sleep(publish_interval)

        except Exception as e:
            logger.error(f"خطأ في حلقة النشر: {e}")
            consecutive_errors += 1
            backoff = min(backoff * 1.5, max_backoff)
            await asyncio.sleep(backoff)

async def run_scheduled_posts_loop_improved(bot):
    consecutive_errors = 0
    backoff = SCHEDULED_POSTS_SLEEP
    max_backoff = 60
    while True:
        try:
            await asyncio.sleep(SCHEDULED_POSTS_SLEEP)
            now_utc = utc_now()
            posts = await db_get_due_scheduled_posts(now_utc)
            for post_id, chat_id, text, fail_count in posts:
                try:
                    await bot.send_message(chat_id, text)
                    await db_delete_scheduled_post(post_id)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    new_fail = fail_count + 1
                    await db_update_scheduled_post_fail(post_id, new_fail)
                    if new_fail >= 5:
                        await db_delete_scheduled_post(post_id)
                        logger.warning(f"تم حذف منشور مجدول بعد 5 محاولات فاشلة: {post_id}")
                    else:
                        logger.error(f"فشل إرسال منشور مجدول: {e}")
            consecutive_errors = 0
            backoff = SCHEDULED_POSTS_SLEEP
        except Exception as e:
            logger.error(f"خطأ في حلقة المنشورات المجدولة: {e}")
            backoff = min(backoff * 1.5, max_backoff)
            await asyncio.sleep(backoff)

async def send_reminders_loop_improved(bot):
    await asyncio.sleep(30)
    asyncio.create_task(daily_reminder_task(bot))
    asyncio.create_task(weekly_reminder_task(bot))
    while True:
        try:
            now = utc_now()
            now_mecca = utc_to_mecca(now)
            today_str = now_mecca.strftime("%Y-%m-%d")
            users_to_remind = await db_get_users_needing_reminder()
            for user_data in users_to_remind:
                user_id = user_data['user_id']
                days_left = user_data['days_left']
                lang = user_data['notification_lang']
                original_lang = user_language.get(user_id, 'ar')
                user_language[user_id] = lang
                text = get_text(user_id, 'subscription_warning').format(days_left)
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("💎 تجديد الاشتراك", callback_data=CallbackData.SUBSCRIBE_MENU), InlineKeyboardButton("🔕 إيقاف التذكير", callback_data=CallbackData.REMINDER_TOGGLE_SUB)]])
                try:
                    await safe_send_markdown(bot, user_id, text, reply_markup=keyboard)
                    await db_update_last_reminder_sent(user_id, "subscription_expiry")
                except:
                    pass
                user_language[user_id] = original_lang
                await asyncio.sleep(0.5)
            await asyncio.sleep(REMINDERS_SLEEP)
        except Exception as e:
            logger.error(f"خطأ في حلقة الإشعارات: {e}")
            await asyncio.sleep(60)

async def daily_reminder_task(bot):
    last_daily_date = None
    while True:
        try:
            now = utc_now()
            now_mecca = utc_to_mecca(now)
            today_str = now_mecca.strftime("%Y-%m-%d")
            if last_daily_date != today_str:
                last_daily_date = today_str
                async def _get_daily_users(conn):
                    cur = await conn.execute("SELECT user_id, notification_lang FROM user_reminder_settings WHERE daily_stats_reminder=1")
                    return await cur.fetchall()
                daily_users = await execute_db(_get_daily_users)
                for user_id, lang in daily_users:
                    original_lang = user_language.get(user_id, 'ar')
                    user_language[user_id] = lang
                    channels = await db_get_user_channels_count(user_id)
                    total_posts = await db_get_user_total_posts(user_id)
                    unpublished = await db_get_user_unpublished_posts(user_id)
                    groups = await db_get_user_groups_count(user_id)
                    text = get_text(user_id, 'daily_stats').format(channels, total_posts, unpublished, groups)
                    try:
                        await safe_send_markdown(bot, user_id, text)
                    except:
                        pass
                    user_language[user_id] = original_lang
                    await asyncio.sleep(0.3)
            await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"خطأ في مهمة الإشعار اليومي: {e}")
            await asyncio.sleep(60)

async def weekly_reminder_task(bot):
    last_weekly_date = None
    while True:
        try:
            now = utc_now()
            now_mecca = utc_to_mecca(now)
            today_str = now_mecca.strftime("%Y-%m-%d")
            if last_weekly_date != today_str and now_mecca.weekday() == 6:
                last_weekly_date = today_str
                async def _get_weekly_users(conn):
                    cur = await conn.execute("SELECT user_id, notification_lang FROM user_reminder_settings WHERE weekly_report=1")
                    return await cur.fetchall()
                weekly_users = await execute_db(_get_weekly_users)
                for user_id, lang in weekly_users:
                    original_lang = user_language.get(user_id, 'ar')
                    user_language[user_id] = lang
                    channels = await db_get_user_channels_count(user_id)
                    total_posts = await db_get_user_total_posts(user_id)
                    unpublished = await db_get_user_unpublished_posts(user_id)
                    groups = await db_get_user_groups_count(user_id)
                    referral_stats = await db_get_referral_stats(user_id)
                    text = get_text(user_id, 'weekly_report').format(channels, total_posts, unpublished, groups, referral_stats['total_referrals'])
                    try:
                        await safe_send_markdown(bot, user_id, text)
                    except:
                        pass
                    user_language[user_id] = original_lang
                    await asyncio.sleep(0.3)
            await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"خطأ في مهمة الإشعار الأسبوعي: {e}")
            await asyncio.sleep(60)

async def cleanup_expired_sessions_improved():
    CLEANUP_SLEEP = 3600
    while True:
        await asyncio.sleep(CLEANUP_SLEEP)
        now = time_module.time()
        async def _cleanup_sessions(conn):
            await conn.execute("DELETE FROM web_sessions WHERE expires < ?", (now,))
            await conn.commit()
        await execute_db(_cleanup_sessions)
        async def _cleanup_tickets(conn):
            cutoff = (utc_now() - timedelta(days=30)).isoformat()
            await conn.execute("DELETE FROM support_tickets WHERE created_at < ? AND status='closed'", (cutoff,))
            await conn.commit()
        await execute_db(_cleanup_tickets)
        logger.info(f"✅ تم تنظيف الجلسات المنتهية والتذاكر القديمة")

async def broadcast_stats_periodically():
    while True:
        await asyncio.sleep(5)
#        total, banned, posts, groups, channels = await db_stats()
        await ws_manager.broadcast({
            'type': 'stats',
            'data': {
                'total_users': total,
                'active_users': total - banned,
                'banned_users': banned,
                'pending_posts': posts,
                'groups': groups,
                'channels': channels
            }
        })

async def auto_close_contests_loop(bot):
    while True:
        await asyncio.sleep(3600)
        try:
            now = utc_now().isoformat()
            async def _get_expired(conn):
                cur = await conn.execute(
                    "SELECT id FROM contests WHERE status = 'active' AND end_date <= ?",
                    (now,)
                )
                return [row[0] for row in await cur.fetchall()]
            expired = await execute_db(_get_expired)

            for contest_id in expired:
                winner_id = await db_get_random_participant(contest_id)

                if winner_id:
                    await db_set_contest_winner(contest_id, winner_id)
                    contest = await db_get_contest(contest_id)
                    try:
                        await bot.send_message(
                            winner_id,
                            f"🏆 **تهانينا!**\nلقد فزت في مسابقة **{contest['title']}**!\n🎁 جائزتك: {contest['prize']}"
                        )
                    except:
                        pass
                    await bot.send_message(
                        PRIMARY_OWNER_ID,
                        f"🤖 تم إغلاق المسابقة #{contest_id} تلقائياً.\nالفائز: {winner_id}"
                    )
                else:
                    async def _close(conn):
                        await conn.execute(
                            "UPDATE contests SET status = 'finished' WHERE id = ?",
                            (contest_id,)
                        )
                        await conn.commit()
                    await execute_db(_close)
        except Exception as e:
            logger.error(f"خطأ في الإغلاق التلقائي للمسابقات: {e}")

async def memory_monitor():
    while True:
        try:
            ram = get_ram_usage()
            if ram['percent'] > 80:
                logger.warning(f"⚠️ استخدام الذاكرة عالي: {ram['percent']}%")
                memory_optimizer()
                logger.info("✅ تم تنظيف الذاكرة")
            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"خطأ في مراقبة الذاكرة: {e}")
            await asyncio.sleep(60)

async def start_web_server():
    try:
        render_port = int(os.getenv("PORT", "0"))
        ports_to_try = []
        if render_port > 0:
            ports_to_try.append(render_port)
        ports_to_try.extend([WEB_PORT, 8080, 10000, 8081, 8082, 8083])

        for port in ports_to_try:
            try:
                runner = web.AppRunner(web_app)
                await runner.setup()
                site = web.TCPSite(runner, WEB_HOST, port)
                await site.start()
                logger.info(f"✅ خادم الويب يعمل على http://{WEB_HOST}:{port}")
                global WEB_PORT_USED
                WEB_PORT_USED = port
                return
            except OSError as e:
                if "address already in use" in str(e):
                    logger.warning(f"⚠️ المنفذ {port} مشغول، جرب المنفذ التالي...")
                    continue
                raise
        logger.error("❌ لا يمكن العثور على منفذ متاح لخادم الويب")
    except Exception as e:
        logger.error(f"❌ فشل تشغيل خادم الويب: {e}")

WEB_PORT_USED = WEB_PORT

async def self_ping_loop():
    await asyncio.sleep(10)
    external_url = os.getenv("RENDER_EXTERNAL_URL", "")
    if external_url:
        url = f"{external_url}/"
    else:
        url = f"http://0.0.0.0:{WEB_PORT_USED}/"

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    logger.info(f"💓 نبض داخلي ناجح: {resp.status}")
        except Exception as e:
            logger.warning(f"⚠️ فشل النبض الداخلي: {e}")
        await asyncio.sleep(600)

# ============================================================
# ===================== تضمين خادم الويب المنفصل =====================
# ============================================================

def import_web_server():
    try:
        import web_server
        web_port = int(os.getenv('WEB_PORT', '8080'))
        web_server.start_web_server_background(web_port)
        logger.info("✅ تم تضمين وتشغيل خادم الويب المنفصل")
        return True
    except ImportError:
        logger.warning("⚠️ لم يتم العثور على ملف web_server.py")
        return False
    except Exception as e:
        logger.error(f"❌ فشل تشغيل خادم الويب المنفصل: {e}")
        return False

# ============================================================
# ===================== تهيئة قاعدة البيانات المحسنة =====================
# ============================================================

async def init_db_improved():
    async with aiosqlite.connect(str(DB_PATH), timeout=DB_TIMEOUT) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute("PRAGMA cache_size=-64000")
        await conn.execute("PRAGMA temp_store=MEMORY")
        await conn.execute("PRAGMA wal_autocheckpoint=1000")
        await conn.execute("PRAGMA optimize")
        await conn.execute("PRAGMA max_page_count=1000000")
        await conn.execute("PRAGMA secure_delete=ON")

        # ========== إنشاء جميع الجداول ==========

        await conn.execute("""
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

        await conn.execute("""
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

        await conn.execute("""
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

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_replies (
                keyword TEXT PRIMARY KEY,
                reply TEXT
            )
        """)

        await conn.execute("""
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
                auto_mute_duration INTEGER DEFAULT 60,
                delete_videos INTEGER DEFAULT 0,
                delete_service INTEGER DEFAULT 0,
                delete_documents INTEGER DEFAULT 0,
                delete_stickers INTEGER DEFAULT 0
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_settings (
                chat_id INTEGER PRIMARY KEY,
                anti_links INTEGER DEFAULT 0,
                anti_badwords INTEGER DEFAULT 0,
                welcome_msg INTEGER DEFAULT 1,
                mute_all INTEGER DEFAULT 0
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id INTEGER PRIMARY KEY
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_groups (
                chat_id INTEGER PRIMARY KEY,
                chat_name TEXT,
                username TEXT,
                added_by INTEGER,
                added_at TIMESTAMP,
                banned INTEGER DEFAULT 0
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_channels (
                channel_id INTEGER PRIMARY KEY,
                channel_name TEXT,
                added_by INTEGER,
                added_at TIMESTAMP,
                banned INTEGER DEFAULT 0
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_messages (
                user_id INTEGER,
                chat_id INTEGER,
                message_time TIMESTAMP,
                PRIMARY KEY (user_id, chat_id)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users_cache (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_updated TEXT
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_warnings (
                user_id INTEGER,
                chat_id INTEGER,
                warnings INTEGER DEFAULT 0,
                PRIMARY KEY(user_id, chat_id)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS banned_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT,
                chat_id INTEGER,
                added_by INTEGER,
                added_at TIMESTAMP,
                UNIQUE(word, chat_id)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hidden_owner_groups (
                chat_id INTEGER PRIMARY KEY,
                owner_id INTEGER,
                is_hidden INTEGER DEFAULT 1
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hidden_admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                admin_id INTEGER NOT NULL,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, admin_id)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_groups_link (
                user_id INTEGER,
                chat_id INTEGER,
                PRIMARY KEY(user_id, chat_id)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_admins (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY(chat_id, user_id)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_levels (
                user_id INTEGER PRIMARY KEY,
                points INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1
            )
        """)

        await conn.execute("""
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

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_locks (
                chat_id INTEGER PRIMARY KEY,
                locked INTEGER DEFAULT 0,
                locked_at TIMESTAMP,
                locked_by INTEGER
            )
        """)

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
                cron_expression TEXT DEFAULT NULL,
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

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS allowed_sendcode_user (
                id INTEGER PRIMARY KEY CHECK (id=1),
                user_id INTEGER
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL,
                referred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_rewarded INTEGER DEFAULT 0,
                UNIQUE(referred_id)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referral_rewards (
                user_id INTEGER PRIMARY KEY,
                referral_count INTEGER DEFAULT 0,
                total_reward_days INTEGER DEFAULT 0,
                claimed_reward_days INTEGER DEFAULT 0
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referral_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        await conn.execute("""
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

        await conn.execute("""
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

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_translation (
                user_id INTEGER PRIMARY KEY,
                lang TEXT DEFAULT 'off'
            )
        """)

        await conn.execute("""
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

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS web_sessions (
                session_id TEXT PRIMARY KEY,
                user_data TEXT,
                expires INTEGER
            )
        """)

        # ========== جداول المسابقات ==========

        await conn.execute("""
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

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contest_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                contest_id INTEGER,
                answer TEXT,
                joined_at TIMESTAMP,
                UNIQUE(user_id, contest_id)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contest_winners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contest_id INTEGER,
                winner_id INTEGER,
                announced_at TIMESTAMP
            )
        """)

        # ========== جدول إعدادات الردود التلقائية ==========

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS auto_reply_settings (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                only_admins INTEGER DEFAULT 0,
                ignore_bots INTEGER DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ========== جدول قوانين المجموعة ==========
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_rules (
                chat_id INTEGER PRIMARY KEY,
                rules_text TEXT,
                set_by INTEGER,
                set_at TIMESTAMP
            )
        """)

        # ========== الفهارس (Indexes) للتحسين ==========

        await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_channel_published ON posts(channel_db_id, published)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_schedule_next ON schedule(next_publish_date)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_channels_user ON user_channels(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_banned_words_chat ON banned_words(chat_id, word)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_messages_time ON user_messages(message_time)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_channel_fail ON posts(channel_db_id, published, fail_count)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_subscription ON users(subscription_end)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_levels_points ON user_levels(points DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_moderation_chat ON moderation_log(chat_id, created_at)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_channel_stats ON channel_stats(channel_db_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_views ON posts(views_count)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_published_views ON posts(published, views_count)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_contests_active ON contests(status, end_date)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_hidden_admins_chat ON hidden_admins(chat_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_schedule_cron ON schedule(cron_expression)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_last_daily ON users(last_daily_reward)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_group_admins_chat ON group_admins(chat_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_group_admins_user ON group_admins(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_group_rules_chat ON group_rules(chat_id)")

        # ========== تحديث الجداول القديمة ==========

        try:
            cursor = await conn.execute("PRAGMA table_info(group_security)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            if 'auto_penalty' not in column_names:
                await conn.execute("ALTER TABLE group_security ADD COLUMN auto_penalty TEXT DEFAULT 'none'")
            if 'auto_mute_duration' not in column_names:
                await conn.execute("ALTER TABLE group_security ADD COLUMN auto_mute_duration INTEGER DEFAULT 60")
            if 'delete_videos' not in column_names:
                await conn.execute("ALTER TABLE group_security ADD COLUMN delete_videos INTEGER DEFAULT 0")
            if 'delete_service' not in column_names:
                await conn.execute("ALTER TABLE group_security ADD COLUMN delete_service INTEGER DEFAULT 0")
            if 'delete_documents' not in column_names:
                await conn.execute("ALTER TABLE group_security ADD COLUMN delete_documents INTEGER DEFAULT 0")
            if 'delete_stickers' not in column_names:
                await conn.execute("ALTER TABLE group_security ADD COLUMN delete_stickers INTEGER DEFAULT 0")
        except Exception as e:
            logger.warning(f"⚠️ فشل تحديث جدول group_security: {e}")

        try:
            cursor = await conn.execute("PRAGMA table_info(users)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            if 'active_channel' not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN active_channel INTEGER DEFAULT NULL")
            if 'referral_code' not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN referral_code TEXT DEFAULT NULL")
            if 'auto_reply_enabled' not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN auto_reply_enabled INTEGER DEFAULT 1")
            if 'auto_recycle' not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN auto_recycle INTEGER DEFAULT 1")
            if 'last_daily_reward' not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN last_daily_reward TEXT DEFAULT NULL")
            if 'last_weekly_reward' not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN last_weekly_reward TEXT DEFAULT NULL")
            if 'achievements' not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN achievements TEXT DEFAULT '[]'")
        except:
            pass

        try:
            cursor = await conn.execute("PRAGMA table_info(posts)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            if 'views_count' not in column_names:
                await conn.execute("ALTER TABLE posts ADD COLUMN views_count INTEGER DEFAULT 0")
            if 'last_view_time' not in column_names:
                await conn.execute("ALTER TABLE posts ADD COLUMN last_view_time TIMESTAMP")
        except:
            pass

        try:
            cursor = await conn.execute("PRAGMA table_info(contests)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            if 'contest_type' not in column_names:
                await conn.execute("ALTER TABLE contests ADD COLUMN contest_type TEXT DEFAULT 'raffle'")
        except:
            pass

        try:
            cursor = await conn.execute("PRAGMA table_info(schedule)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            if 'cron_expression' not in column_names:
                await conn.execute("ALTER TABLE schedule ADD COLUMN cron_expression TEXT DEFAULT NULL")
        except:
            pass

        # ========== إدراج البيانات الافتراضية ==========

        await conn.execute("INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)", (PRIMARY_OWNER_ID,))

        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('publish_interval', ?)", (str(DEFAULT_PUBLISH_INTERVAL_SECONDS),))
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('updates_channel', '')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('force_subscribe_enabled', '0')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('force_subscribe_channel', '')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_backup', '1')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_backup', '')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_ticket_number', '0')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('log_channel_id', '')")

        await conn.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('reward_days_per_referral', '3')")
        await conn.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('referral_bonus_points', '50')")
        await conn.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('max_referrals_per_day', '5')")
        await conn.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('welcome_bonus_points', '10')")

        await conn.commit()

    await db_pool.initialize()
    await cache_manager.init()

    logger.info("✅ قاعدة البيانات جاهزة مع جميع الجداول والتحسينات")
    logger.info("✅ تم إنشاء 40+ جدول و 20+ فهرس")

# ===== استيراد الكلمات المحظورة من ملف عند التشغيل =====
async def import_banned_words_on_startup():
    """استيراد الكلمات المحظورة من ملف عند بدء التشغيل"""
    try:
        words = load_banned_words_from_file(BANNED_WORDS_FILE)
        if words:
            async def _import(conn):
                imported = 0
                for word in words:
                    try:
                        await conn.execute(
                            "INSERT OR IGNORE INTO banned_words (word, chat_id, added_by, added_at) VALUES (?, ?, ?, ?)",
                            (word, -1, PRIMARY_OWNER_ID, utc_now_iso())
                        )
                        imported += 1
                    except:
                        continue
                await conn.commit()
                return imported
            imported_count = await execute_db(_import)
            logger.info(f"✅ تم استيراد {imported_count} كلمة محظورة من {BANNED_WORDS_FILE}")
        else:
            logger.info(f"📭 لا توجد كلمات محظورة في {BANNED_WORDS_FILE} للاستيراد")
    except Exception as e:
        logger.error(f"❌ فشل استيراد الكلمات المحظورة: {e}")

# ===================================================================
# ===================== إضافة أوامر /set_rules و /rules =====================
# ===================================================================

async def set_rules_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين قوانين المجموعة"""
    if update.message is None:
        return
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return

    chat_id = chat.id
    user_id = user.id

    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "📝 **تعيين قوانين المجموعة**\n\n"
            "استخدم الأمر مع النص المراد تعيينه كقوانين:\n"
            "`/set_rules نص القوانين`\n\n"
            "📌 مثال:\n"
            "`/set_rules 1- احترام الأعضاء\n2- عدم إرسال روابط\n3- الالتزام بالآداب العامة`"
        )
        return

    rules_text = " ".join(args)
    rules_text = sanitize_text(rules_text, max_length=4000)

    async def _set_rules(conn):
        await conn.execute(
            "INSERT OR REPLACE INTO group_rules (chat_id, rules_text, set_by, set_at) VALUES (?, ?, ?, ?)",
            (chat_id, rules_text, user_id, utc_now_iso())
        )
        await conn.commit()

    await execute_db(_set_rules)

    await update.message.reply_text(
        f"✅ **تم تعيين قوانين المجموعة بنجاح!**\n\n"
        f"📌 لعرض القوانين استخدم الأمر `/rules`",
        parse_mode="MarkdownV2"
    )

async def rules_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قوانين المجموعة"""
    if update.message is None:
        return
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return

    chat_id = chat.id

    async def _get_rules(conn):
        cur = await conn.execute(
            "SELECT rules_text, set_by, set_at FROM group_rules WHERE chat_id=?",
            (chat_id,)
        )
        return await cur.fetchone()

    rules_data = await execute_db(_get_rules)

    if not rules_data or not rules_data[0]:
        await update.message.reply_text(
            "📜 **لا توجد قوانين مسجلة لهذه المجموعة.**\n\n"
            "يمكن للمشرفين تعيين القوانين باستخدام:\n"
            "`/set_rules نص القوانين`"
        )
        return

    rules_text = rules_data[0]
    set_by = rules_data[1]
    set_at = rules_data[2]

    try:
        set_at_dt = datetime.fromisoformat(set_at)
        set_at_mecca = utc_to_mecca(set_at_dt)
        set_at_str = set_at_mecca.strftime("%Y-%m-%d %H:%M")
    except:
        set_at_str = set_at[:16] if set_at else "تاريخ غير معروف"

    message = f"📜 **قوانين المجموعة**\n━━━━━━━━━━━━━━━━━━━━━━\n\n{rules_text}\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
    message += f"📌 تم التعيين بواسطة: `{set_by}`\n"
    message += f"🕐 التاريخ: {set_at_str}"

    await safe_send_markdown(context.bot, chat_id, message)

# ===================================================================

# ===== الوظيفة الرئيسية =====
async def main():
    await init_db_improved()

    # استيراد الكلمات المحظورة من ملف
    await import_banned_words_on_startup()

    # تحميل اللغات من الملفات
    load_all_languages()

    # تحسينات الذاكرة
    task_manager.create_task(memory_optimizer_loop())

    if USE_PROXY:
        request_kwargs = {
            'proxy_url': PROXY_URL,
            'read_timeout': 60.0,
            'write_timeout': 30.0,
            'connect_timeout': 30.0,
            'pool_timeout': 10.0,
            'connection_pool_size': MAX_CONNECTIONS
        }
        request = HTTPXRequest(**request_kwargs)
        application = Application.builder().token(TOKEN).request(request).build()
    else:
        request_kwargs = {
            'read_timeout': 60.0,
            'write_timeout': 30.0,
            'connect_timeout': 30.0,
            'pool_timeout': 10.0,
            'connection_pool_size': MAX_CONNECTIONS
        }
        request = HTTPXRequest(**request_kwargs)
        application = Application.builder().token(TOKEN).request(request).build()

    application.add_error_handler(global_error_handler)

    # ========== Command Handlers ==========
    application.add_handler(CommandHandler("start", start_command_handler))
    application.add_handler(CommandHandler("language", language_command_handler))
    application.add_handler(CommandHandler("syncgroup", syncgroup_command_handler))
    application.add_handler(CommandHandler("security", security_command_handler))
    application.add_handler(CommandHandler("register_hidden_owner", register_hidden_owner_handler))
    application.add_handler(CommandHandler("add_hidden_admin", add_hidden_admin_command))
    application.add_handler(CommandHandler("remove_hidden_admin", remove_hidden_admin_command))
    application.add_handler(CommandHandler("list_hidden_admins", list_hidden_admins_command))
    application.add_handler(CommandHandler("trial", trial_command_handler))
    application.add_handler(CommandHandler("subscribe", subscribe_command_handler))
    application.add_handler(CommandHandler("help", help_command_handler))
    application.add_handler(CommandHandler("support", support_command_handler))
    application.add_handler(CommandHandler("support_reply", support_reply_command_handler))
    application.add_handler(CommandHandler("rank", rank_command_handler))
    application.add_handler(CommandHandler("top", top_command_handler))
    application.add_handler(CommandHandler("developer", developer_command_handler))
    application.add_handler(CommandHandler("updates", updates_command_handler))
    application.add_handler(CommandHandler("stats", stats_command_handler))
    application.add_handler(CommandHandler("sendcode", sendcode_command_handler))
    application.add_handler(CommandHandler("lock", lock_chat_command_handler))
    application.add_handler(CommandHandler("unlock", unlock_chat_command_handler))
    application.add_handler(CommandHandler("schedule", schedule_post_command_handler))
    application.add_handler(CommandHandler("panel", panel_command_handler))
    application.add_handler(CommandHandler("set_log_channel", set_log_channel_command_handler))
    application.add_handler(CommandHandler("ban", handle_moderation_commands))
    application.add_handler(CommandHandler("mute", handle_moderation_commands))
    application.add_handler(CommandHandler("warn", handle_moderation_commands))
    application.add_handler(CommandHandler("kick", handle_moderation_commands))
    application.add_handler(CommandHandler("restrict", handle_moderation_commands))
    application.add_handler(CommandHandler("pin", handle_moderation_commands))
    application.add_handler(CommandHandler("unban", handle_moderation_commands))
    application.add_handler(CommandHandler("contests", contests_command_handler))
    application.add_handler(CommandHandler("create_contest", create_contest_command_handler))
    application.add_handler(CommandHandler("declare_winner", declare_winner_command_handler))
    application.add_handler(CommandHandler("set_rules", set_rules_command_handler))
    application.add_handler(CommandHandler("rules", rules_command_handler))

    # ========== CallbackQuery Handlers ==========
    application.add_handler(CallbackQueryHandler(lang_callback_handler, pattern="^lang_"))
    application.add_handler(CallbackQueryHandler(handle_text_callbacks, pattern="^(rank|top|schedule_post|language)$"))
    application.add_handler(CallbackQueryHandler(main_menu_callback, pattern=f"^{CallbackData.MAIN_MENU}$"))
    application.add_handler(CallbackQueryHandler(back_callback, pattern=f"^{CallbackData.BACK}$"))
    application.add_handler(CallbackQueryHandler(cancel_session_callback, pattern=f"^{CallbackData.CANCEL_SESSION}$"))
    application.add_handler(CallbackQueryHandler(add_channel_callback, pattern=f"^{CallbackData.CHANNELS_ADD}$"))
    application.add_handler(CallbackQueryHandler(my_channels_callback, pattern=f"^{CallbackData.CHANNELS_MY}$"))
    application.add_handler(CallbackQueryHandler(delete_channel_callback, pattern=f"^{CallbackData.CHANNELS_DELETE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(select_channel_callback, pattern=f"^{CallbackData.CHANNELS_SELECT_PREFIX}"))
    application.add_handler(CallbackQueryHandler(add_15_posts_callback, pattern=f"^{CallbackData.POSTS_ADD_15}$"))
    application.add_handler(CallbackQueryHandler(publish_one_callback, pattern=f"^{CallbackData.POSTS_PUBLISH_ONE}$"))
    application.add_handler(CallbackQueryHandler(my_posts_callback, pattern=f"^{CallbackData.POSTS_MY}$"))
    application.add_handler(CallbackQueryHandler(recycle_posts_callback, pattern=f"^{CallbackData.POSTS_RECYCLE}$"))
    application.add_handler(CallbackQueryHandler(delete_single_post_callback, pattern=f"^{CallbackData.POSTS_DELETE_SINGLE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(confirm_clear_all_posts_callback, pattern=f"^{CallbackData.POSTS_CONFIRM_CLEAR_ALL_PREFIX}"))
    application.add_handler(CallbackQueryHandler(clear_all_posts_callback, pattern=f"^{CallbackData.POSTS_CLEAR_ALL_PREFIX}"))
    application.add_handler(CallbackQueryHandler(my_pending_stats_callback, pattern=f"^{CallbackData.STATS_PENDING}$"))
    application.add_handler(CallbackQueryHandler(my_full_stats_callback, pattern=f"^{CallbackData.STATS_FULL}$"))
    application.add_handler(CallbackQueryHandler(my_groups_callback, pattern=f"^{CallbackData.GROUPS_MY}$"))
    application.add_handler(CallbackQueryHandler(group_settings_callback, pattern=f"^{CallbackData.GROUPS_SETTINGS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(settings_menu_callback, pattern=f"^{CallbackData.SETTINGS_MENU}$"))
    application.add_handler(CallbackQueryHandler(toggle_auto_publish_callback, pattern=f"^{CallbackData.SETTINGS_TOGGLE_AUTO_PUBLISH}$"))
    application.add_handler(CallbackQueryHandler(toggle_auto_recycle_callback, pattern=f"^{CallbackData.SETTINGS_TOGGLE_AUTO_RECYCLE}$"))
    application.add_handler(CallbackQueryHandler(schedule_menu_callback, pattern=f"^{CallbackData.SCHEDULE_MENU_PREFIX}"))
    application.add_handler(CallbackQueryHandler(set_interval_minutes_callback, pattern=f"^{CallbackData.SCHEDULE_SET_INTERVAL_MINUTES_PREFIX}"))
    application.add_handler(CallbackQueryHandler(set_interval_hours_callback, pattern=f"^{CallbackData.SCHEDULE_SET_INTERVAL_HOURS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(set_interval_days_callback, pattern=f"^{CallbackData.SCHEDULE_SET_INTERVAL_DAYS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(set_cron_callback, pattern="^schedule:set_cron:"))
    application.add_handler(CallbackQueryHandler(set_days_callback, pattern=f"^{CallbackData.SCHEDULE_SET_DAYS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(set_dates_callback, pattern=f"^{CallbackData.SCHEDULE_SET_DATES_PREFIX}"))
    application.add_handler(CallbackQueryHandler(set_publish_time_callback, pattern=f"^{CallbackData.SCHEDULE_SET_PUBLISH_TIME_PREFIX}"))
    application.add_handler(CallbackQueryHandler(day_select_callback, pattern=f"^{CallbackData.SCHEDULE_DAY_SELECT_PREFIX}"))
    application.add_handler(CallbackQueryHandler(save_days_callback, pattern=f"^{CallbackData.SCHEDULE_SAVE_DAYS}$"))
    application.add_handler(CallbackQueryHandler(security_links_callback, pattern=f"^{CallbackData.SECURITY_LINKS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_mentions_callback, pattern=f"^{CallbackData.SECURITY_MENTIONS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_warn_callback, pattern=f"^{CallbackData.SECURITY_WARN_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_slowmode_callback, pattern=f"^{CallbackData.SECURITY_SLOWMODE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_banned_words_menu_callback, pattern=f"^{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_welcome_callback, pattern=f"^{CallbackData.SECURITY_WELCOME_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_goodbye_callback, pattern=f"^{CallbackData.SECURITY_GOODBYE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_close_callback, pattern=f"^{CallbackData.SECURITY_CLOSE}$"))
    application.add_handler(CallbackQueryHandler(security_main_callback, pattern=f"^{CallbackData.SECURITY_MAIN}$"))
    application.add_handler(CallbackQueryHandler(banned_words_add_callback, pattern=f"^{CallbackData.BANNED_WORDS_ADD_PREFIX}"))
    application.add_handler(CallbackQueryHandler(banned_words_list_callback, pattern=f"^{CallbackData.BANNED_WORDS_LIST_PREFIX}"))
    application.add_handler(CallbackQueryHandler(banned_words_remove_callback, pattern=f"^{CallbackData.BANNED_WORDS_REMOVE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(help_callback, pattern=f"^{CallbackData.HELP}$"))
    application.add_handler(CallbackQueryHandler(support_menu_callback, pattern=f"^{CallbackData.SUPPORT_MENU}$"))
    application.add_handler(CallbackQueryHandler(support_help_callback, pattern=f"^{CallbackData.SUPPORT_HELP}$"))
    application.add_handler(CallbackQueryHandler(support_ticket_callback, pattern=f"^{CallbackData.SUPPORT_TICKET}$"))
    application.add_handler(CallbackQueryHandler(support_back_callback, pattern=f"^{CallbackData.SUPPORT_BACK}$"))
    application.add_handler(CallbackQueryHandler(trial_callback, pattern=f"^{CallbackData.TRIAL}$"))
    application.add_handler(CallbackQueryHandler(subscribe_menu_callback, pattern=f"^{CallbackData.SUBSCRIBE_MENU}$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_1_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_1}$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_2_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_2}$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_30_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_30}$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_90_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_90}$"))
    application.add_handler(CallbackQueryHandler(developer_callback, pattern=f"^{CallbackData.DEVELOPER}$"))
    application.add_handler(CallbackQueryHandler(updates_callback, pattern=f"^{CallbackData.UPDATES}$"))
    application.add_handler(CallbackQueryHandler(referral_menu_callback, pattern=f"^{CallbackData.REFERRAL_MENU}$"))
    application.add_handler(CallbackQueryHandler(referral_copy_link_callback, pattern=f"^{CallbackData.REFERRAL_COPY_LINK_PREFIX}"))
    application.add_handler(CallbackQueryHandler(referral_claim_reward_callback, pattern=f"^{CallbackData.REFERRAL_CLAIM_REWARD}$"))
    application.add_handler(CallbackQueryHandler(referral_list_callback, pattern=f"^{CallbackData.REFERRAL_LIST}$"))
    application.add_handler(CallbackQueryHandler(reminder_menu_callback, pattern=f"^{CallbackData.REMINDER_MENU}$"))
    application.add_handler(CallbackQueryHandler(reminder_toggle_sub_callback, pattern=f"^{CallbackData.REMINDER_TOGGLE_SUB}$"))
    application.add_handler(CallbackQueryHandler(reminder_toggle_daily_callback, pattern=f"^{CallbackData.REMINDER_TOGGLE_DAILY}$"))
    application.add_handler(CallbackQueryHandler(reminder_toggle_weekly_callback, pattern=f"^{CallbackData.REMINDER_TOGGLE_WEEKLY}$"))
    application.add_handler(CallbackQueryHandler(reminder_set_days_callback, pattern=f"^{CallbackData.REMINDER_SET_DAYS}$"))
    application.add_handler(CallbackQueryHandler(reminder_set_lang_callback, pattern=f"^{CallbackData.REMINDER_SET_LANG}$"))
    application.add_handler(CallbackQueryHandler(reminder_lang_callback, pattern=f"^{CallbackData.REMINDER_LANG_PREFIX}"))
    application.add_handler(CallbackQueryHandler(translation_menu_callback, pattern=f"^{CallbackData.TRANSLATION_MENU}$"))
    application.add_handler(CallbackQueryHandler(translation_off_callback, pattern=f"^{CallbackData.TRANSLATION_OFF}$"))
    application.add_handler(CallbackQueryHandler(translation_set_callback, pattern=f"^{CallbackData.TRANSLATION_SET_PREFIX}"))
    application.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=f"^{CallbackData.ADMIN_PANEL}$"))
    application.add_handler(CallbackQueryHandler(admin_users_callback, pattern=f"^{CallbackData.ADMIN_USERS}$"))
    application.add_handler(CallbackQueryHandler(admin_banned_users_callback, pattern=f"^{CallbackData.ADMIN_BANNED_USERS}$"))
    application.add_handler(CallbackQueryHandler(admin_unban_all_users_callback, pattern=f"^{CallbackData.ADMIN_UNBAN_ALL_USERS}$"))
    application.add_handler(CallbackQueryHandler(admin_all_channels_callback, pattern=f"^{CallbackData.ADMIN_ALL_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_banned_channels_callback, pattern=f"^{CallbackData.ADMIN_BANNED_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_activate_all_channels_callback, pattern=f"^{CallbackData.ADMIN_ACTIVATE_ALL_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_groups_callback, pattern=f"^{CallbackData.ADMIN_GROUPS}$"))
    application.add_handler(CallbackQueryHandler(admin_banned_groups_callback, pattern=f"^{CallbackData.ADMIN_BANNED_GROUPS}$"))
    application.add_handler(CallbackQueryHandler(admin_unban_all_groups_callback, pattern=f"^{CallbackData.ADMIN_UNBAN_ALL_GROUPS}$"))
    application.add_handler(CallbackQueryHandler(admin_bot_channels_callback, pattern=f"^{CallbackData.ADMIN_BOT_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_banned_bot_channels_callback, pattern=f"^{CallbackData.ADMIN_BANNED_BOT_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_unban_all_bot_channels_callback, pattern=f"^{CallbackData.ADMIN_UNBAN_ALL_BOT_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_monitor_users_callback, pattern=f"^{CallbackData.ADMIN_MONITOR_USERS}$"))
    application.add_handler(CallbackQueryHandler(admin_add_admin_callback, pattern=f"^{CallbackData.ADMIN_ADD_ADMIN}$"))
    application.add_handler(CallbackQueryHandler(admin_remove_admin_callback, pattern=f"^{CallbackData.ADMIN_REMOVE_ADMIN}$"))
    application.add_handler(CallbackQueryHandler(admin_ram_callback, pattern=f"^{CallbackData.ADMIN_RAM}$"))
    application.add_handler(CallbackQueryHandler(admin_stats_callback, pattern=f"^{CallbackData.ADMIN_STATS}$"))
    application.add_handler(CallbackQueryHandler(admin_metrics_callback, pattern=f"^{CallbackData.ADMIN_METRICS}$"))
    application.add_handler(CallbackQueryHandler(admin_backup_callback, pattern=f"^{CallbackData.ADMIN_BACKUP}$"))
    application.add_handler(CallbackQueryHandler(admin_restore_backup_callback, pattern=f"^{CallbackData.ADMIN_RESTORE_BACKUP}$"))
    application.add_handler(CallbackQueryHandler(admin_restore_backup_select_callback, pattern=f"^{CallbackData.ADMIN_RESTORE_BACKUP_SELECT_PREFIX}"))
    application.add_handler(CallbackQueryHandler(admin_backup_settings_callback, pattern=f"^{CallbackData.ADMIN_BACKUP_SETTINGS}$"))
    application.add_handler(CallbackQueryHandler(admin_toggle_auto_backup_callback, pattern=f"^{CallbackData.ADMIN_TOGGLE_AUTO_BACKUP}$"))
    application.add_handler(CallbackQueryHandler(admin_change_interval_callback, pattern=f"^{CallbackData.ADMIN_CHANGE_INTERVAL}$"))
    application.add_handler(CallbackQueryHandler(admin_send_update_callback, pattern=f"^{CallbackData.ADMIN_SEND_UPDATE}$"))
    application.add_handler(CallbackQueryHandler(admin_set_update_channel_callback, pattern=f"^{CallbackData.ADMIN_SET_UPDATE_CHANNEL}$"))
    application.add_handler(CallbackQueryHandler(admin_show_update_channel_callback, pattern=f"^{CallbackData.ADMIN_SHOW_UPDATE_CHANNEL}$"))
    application.add_handler(CallbackQueryHandler(admin_updates_callback, pattern=f"^{CallbackData.ADMIN_UPDATES}$"))
    application.add_handler(CallbackQueryHandler(admin_force_subscribe_callback, pattern=f"^{CallbackData.ADMIN_FORCE_SUBSCRIBE}$"))
    application.add_handler(CallbackQueryHandler(admin_set_force_channel_callback, pattern=f"^{CallbackData.ADMIN_SET_FORCE_CHANNEL}$"))
    application.add_handler(CallbackQueryHandler(admin_broadcast_callback, pattern=f"^{CallbackData.ADMIN_BROADCAST}$"))
    application.add_handler(CallbackQueryHandler(admin_confirm_broadcast_callback, pattern=f"^{CallbackData.ADMIN_CONFIRM_BROADCAST}$"))
    application.add_handler(CallbackQueryHandler(admin_support_tickets_callback, pattern=f"^{CallbackData.ADMIN_SUPPORT_TICKETS}$"))
    application.add_handler(CallbackQueryHandler(admin_delete_all_tickets_callback, pattern=f"^{CallbackData.ADMIN_DELETE_ALL_TICKETS}$"))
    application.add_handler(CallbackQueryHandler(admin_confirm_delete_tickets_callback, pattern=f"^{CallbackData.ADMIN_CONFIRM_DELETE_TICKETS}$"))
    application.add_handler(CallbackQueryHandler(admin_manage_sendcode_callback, pattern=f"^{CallbackData.ADMIN_MANAGE_SENDCODE}$"))
    application.add_handler(CallbackQueryHandler(admin_set_sendcode_user_callback, pattern=f"^{CallbackData.ADMIN_SET_SENDCODE_USER}$"))
    application.add_handler(CallbackQueryHandler(admin_show_log_channel_callback, pattern=f"^{CallbackData.ADMIN_SHOW_LOG_CHANNEL}$"))
    application.add_handler(CallbackQueryHandler(admin_set_log_channel_callback, pattern=f"^{CallbackData.ADMIN_SET_LOG_CHANNEL}$"))
    application.add_handler(CallbackQueryHandler(admin_replies_callback, pattern=f"^{CallbackData.ADMIN_REPLIES}$"))
    application.add_handler(CallbackQueryHandler(admin_add_reply_callback, pattern=f"^{CallbackData.ADMIN_ADD_REPLY}$"))
    application.add_handler(CallbackQueryHandler(admin_list_replies_callback, pattern=f"^{CallbackData.ADMIN_LIST_REPLIES}$"))
    application.add_handler(CallbackQueryHandler(admin_del_reply_callback, pattern=f"^{CallbackData.ADMIN_DEL_REPLY}$"))
    application.add_handler(CallbackQueryHandler(admin_del_reply_callback, pattern="^admin_del_reply_"))
    application.add_handler(CallbackQueryHandler(admin_banned_words_callback, pattern=f"^{CallbackData.ADMIN_BANNED_WORDS}$"))
    application.add_handler(CallbackQueryHandler(admin_add_banned_word_callback, pattern=f"^{CallbackData.ADMIN_ADD_BANNED_WORD}$"))
    application.add_handler(CallbackQueryHandler(admin_list_banned_words_callback, pattern=f"^{CallbackData.ADMIN_LIST_BANNED_WORDS}$"))
    application.add_handler(CallbackQueryHandler(admin_remove_banned_word_callback, pattern=f"^{CallbackData.ADMIN_REMOVE_BANNED_WORD}$"))
    application.add_handler(CallbackQueryHandler(admin_del_banned_word_callback, pattern="^admin_del_banned_word_"))

    # ===== معالجات التحكم في الردود =====
    application.add_handler(CallbackQueryHandler(auto_reply_toggle_callback, pattern=f"^{CallbackData.AUTO_REPLY_TOGGLE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_admins_callback, pattern=f"^{CallbackData.AUTO_REPLY_ADMINS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_reset_callback, pattern=f"^{CallbackData.AUTO_REPLY_RESET_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_confirm_reset_callback, pattern=f"^{CallbackData.AUTO_REPLY_CONFIRM_RESET_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_cancel_callback, pattern=f"^{CallbackData.AUTO_REPLY_CANCEL_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_stats_callback, pattern=f"^{CallbackData.AUTO_REPLY_STATS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(user_auto_reply_toggle_callback, pattern=f"^{CallbackData.USER_AUTO_REPLY_TOGGLE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(admin_auto_reply_callback, pattern=f"^{CallbackData.ADMIN_AUTO_REPLY}$"))
    application.add_handler(CallbackQueryHandler(admin_auto_reply_select_callback, pattern=f"^{CallbackData.ADMIN_AUTO_REPLY_SELECT_PREFIX}"))

    # ===== معالجات NSFW =====
    application.add_handler(CallbackQueryHandler(nsfw_settings_callback, pattern=f"^{CallbackData.NSFW_SETTINGS}$"))
    application.add_handler(CallbackQueryHandler(nsfw_toggle_callback, pattern=f"^{CallbackData.NSFW_TOGGLE}$"))
    application.add_handler(CallbackQueryHandler(nsfw_threshold_callback, pattern=f"^{CallbackData.NSFW_THRESHOLD_SET}$"))

    application.add_handler(CallbackQueryHandler(contests_menu_callback, pattern=f"^{CallbackData.CONTESTS_MENU}$"))
    application.add_handler(CallbackQueryHandler(contest_join_callback, pattern=f"^{CallbackData.CONTEST_JOIN_PREFIX}"))
    application.add_handler(CallbackQueryHandler(contest_winners_callback, pattern=f"^{CallbackData.CONTEST_WINNERS}$"))
    application.add_handler(CallbackQueryHandler(contests_back_callback, pattern=f"^{CallbackData.CONTESTS_BACK}$"))
    application.add_handler(CallbackQueryHandler(admin_create_contest_callback, pattern=f"^{CallbackData.ADMIN_CREATE_CONTEST}$"))
    application.add_handler(CallbackQueryHandler(admin_declare_winner_callback, pattern=f"^{CallbackData.ADMIN_DECLARE_WINNER}$"))

    application.add_handler(CallbackQueryHandler(admin_toggle_channel_ban_callback, pattern=f"^{CallbackData.ADMIN_TOGGLE_CHANNEL_BAN_PREFIX}"))
    application.add_handler(CallbackQueryHandler(admin_toggle_group_ban_callback, pattern=f"^{CallbackData.ADMIN_TOGGLE_GROUP_BAN_PREFIX}"))
    application.add_handler(CallbackQueryHandler(channel_stats_callback, pattern=f"^{CallbackData.CHANNEL_STATS}:"))
    application.add_handler(CallbackQueryHandler(channel_growth_callback, pattern=f"^{CallbackData.CHANNEL_GROWTH}:"))
    application.add_handler(CallbackQueryHandler(channel_stats_refresh_callback, pattern=f"^{CallbackData.CHANNEL_STATS_REFRESH}:"))
    application.add_handler(CallbackQueryHandler(my_channel_stats_callback, pattern=f"^{CallbackData.MY_CHANNEL_STATS}$"))
    application.add_handler(CallbackQueryHandler(check_subscribe_callback_handler, pattern=f"^{CallbackData.CHECK_SUBSCRIBE}$"))
    application.add_handler(CallbackQueryHandler(panel_lock_callback_handler, pattern=f"^{CallbackData.PANEL_LOCK_PREFIX}"))
    application.add_handler(CallbackQueryHandler(panel_unlock_callback_handler, pattern=f"^{CallbackData.PANEL_UNLOCK_PREFIX}"))
    application.add_handler(CallbackQueryHandler(panel_close_callback_handler, pattern=f"^{CallbackData.PANEL_CLOSE}$"))
    application.add_handler(CallbackQueryHandler(advanced_actions_callback, pattern=f"^{CallbackData.ADVANCED_ACTIONS}:"))
    application.add_handler(CallbackQueryHandler(group_action_ban_callback, pattern=f"^{CallbackData.GROUP_ACTION_BAN}:"))
    application.add_handler(CallbackQueryHandler(group_action_mute_callback, pattern=f"^{CallbackData.GROUP_ACTION_MUTE}:"))
    application.add_handler(CallbackQueryHandler(advanced_mute_duration_callback, pattern="^adv_mute_duration:"))
    application.add_handler(CallbackQueryHandler(group_action_warn_callback, pattern=f"^{CallbackData.GROUP_ACTION_WARN}:"))
    application.add_handler(CallbackQueryHandler(group_action_kick_callback, pattern=f"^{CallbackData.GROUP_ACTION_KICK}:"))
    application.add_handler(CallbackQueryHandler(group_action_restrict_callback, pattern=f"^{CallbackData.GROUP_ACTION_RESTRICT}:"))
    application.add_handler(CallbackQueryHandler(group_action_pin_callback, pattern=f"^{CallbackData.GROUP_ACTION_PIN}:"))
    application.add_handler(CallbackQueryHandler(group_action_log_callback, pattern=f"^{CallbackData.GROUP_ACTION_LOG}:"))
    application.add_handler(CallbackQueryHandler(group_action_unban_callback, pattern=f"^{CallbackData.GROUP_ACTION_UNBAN}:"))
    application.add_handler(CallbackQueryHandler(security_select_group_callback, pattern=f"^{CallbackData.SECURITY_SELECT_GROUP}"))
    application.add_handler(CallbackQueryHandler(security_refresh_groups_callback, pattern=f"^{CallbackData.SECURITY_REFRESH_GROUPS}$"))
    application.add_handler(CallbackQueryHandler(penalty_menu_callback, pattern=f"^{CallbackData.PENALTY_MENU}:"))
    application.add_handler(CallbackQueryHandler(penalty_kick_callback, pattern=f"^{CallbackData.PENALTY_KICK}:"))
    application.add_handler(CallbackQueryHandler(penalty_ban_callback, pattern=f"^{CallbackData.PENALTY_BAN}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_callback, pattern=f"^{CallbackData.PENALTY_MUTE}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_5}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_30}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_60}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_720}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_1440}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_10080}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_PERMANENT}:"))
    application.add_handler(CallbackQueryHandler(publish_all_channels_callback_handler, pattern=f"^{CallbackData.PUBLISH_ALL_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(delete_group_callback, pattern="^delete_group:"))

    # ===== الأزرار الجديدة =====
    application.add_handler(CallbackQueryHandler(security_delete_videos_callback, pattern=f"^{CallbackData.SECURITY_DELETE_VIDEOS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_delete_service_callback, pattern=f"^{CallbackData.SECURITY_DELETE_SERVICE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_delete_documents_callback, pattern=f"^{CallbackData.SECURITY_DELETE_DOCUMENTS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_delete_stickers_callback, pattern=f"^{CallbackData.SECURITY_DELETE_STICKERS_PREFIX}"))

    application.add_handler(PreCheckoutQueryHandler(pre_checkout_callback_handler))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback_handler))

    application.add_handler(ChatMemberHandler(track_chat_add, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_bot_added))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))
    application.add_handler(MessageHandler(filters.CAPTION & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, message_handler_main))
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.AUDIO & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.VOICE & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.ANIMATION & filters.ChatType.PRIVATE, message_handler_main))

    # ===== إضافة معالج حذف رسائل الخدمة المنفصل =====
    application.add_handler(MessageHandler(filters.StatusUpdate.ALL, delete_service_messages))

    commands = [
        BotCommand("start", "بدء البوت"),
        BotCommand("trial", "تجربة مجانية"),
        BotCommand("subscribe", "الاشتراك"),
        BotCommand("syncgroup", "تفعيل المجموعة"),
        BotCommand("security", "إعدادات الأمان"),
        BotCommand("register_hidden_owner", "تسجيل مالك مخفي"),
        BotCommand("add_hidden_admin", "إضافة مشرف مخفي"),
        BotCommand("remove_hidden_admin", "إزالة مشرف مخفي"),
        BotCommand("list_hidden_admins", "عرض المشرفين المخفيين"),
        BotCommand("rank", "رتبتك"),
        BotCommand("top", "أفضل 10"),
        BotCommand("stats", "إحصائيات القناة"),
        BotCommand("lock", "قفل المجموعة"),
        BotCommand("unlock", "فتح المجموعة"),
        BotCommand("schedule", "جدولة منشور"),
        BotCommand("panel", "لوحة التحكم"),
        BotCommand("language", "تغيير اللغة"),
        BotCommand("support", "مركز الدعم"),
        BotCommand("support_reply", "الرد على تذكرة"),
        BotCommand("help", "المساعدة"),
        BotCommand("developer", "المطور"),
        BotCommand("updates", "آخر التحديثات"),
        BotCommand("sendcode", "إرسال كود البوت"),
        BotCommand("set_log_channel", "تعيين قناة التقارير"),
        BotCommand("ban", "حظر مستخدم"),
        BotCommand("mute", "كتم مستخدم"),
        BotCommand("warn", "تحذير مستخدم"),
        BotCommand("kick", "طرد مستخدم"),
        BotCommand("restrict", "تقييد مستخدم"),
        BotCommand("pin", "تثبيت رسالة"),
        BotCommand("unban", "إلغاء حظر مستخدم"),
        BotCommand("contests", "المسابقات"),
        BotCommand("create_contest", "إنشاء مسابقة"),
        BotCommand("declare_winner", "إعلان فائز"),
        BotCommand("set_rules", "تعيين قوانين المجموعة"),
        BotCommand("rules", "عرض قوانين المجموعة"),
    ]
    await application.bot.set_my_commands(commands)

    # ===== تضمين خادم الويب المنفصل =====
    web_imported = import_web_server()

    task_manager.create_task(auto_publish_loop_improved(application.bot))
    task_manager.create_task(auto_backup())
    task_manager.create_task(run_scheduled_posts_loop_improved(application.bot))
    task_manager.create_task(send_reminders_loop_improved(application.bot))
    task_manager.create_task(cleanup_expired_sessions_improved())
    task_manager.create_task(start_web_server())
    task_manager.create_task(self_ping_loop())
    task_manager.create_task(broadcast_stats_periodically())
    task_manager.create_task(cleanup_points_cache())
    task_manager.create_task(memory_monitor())
    task_manager.create_task(auto_close_contests_loop(application.bot))

    print(f"🚀 تم تشغيل {BOT_NAME} (الإصدار 19.3.3)")
    print("✅ جميع التحسينات المطلوبة تم تطبيقها:")
    print("   • ✅ أزرار جديدة: حذف الفيديوهات، رسائل الخدمة، الملفات، الملصقات")
    print("   • ✅ تحديث قاعدة البيانات (group_security)")
    print("   • ✅ تحسين filter_messages_handler")
    print("   • ✅ إضافة معالجات الكولباك الجديدة")
    print("   • ✅ تحديث لوحة الأمان security_keyboard")
    print("   • ✅ إصلاح شاملة للكود")

    try:
        await application.run_polling(
            drop_pending_updates=True,
            poll_interval=POLL_INTERVAL
        )
    except asyncio.CancelledError:
        logger.info("🛑 تم إلغاء تشغيل البوت")
    except KeyboardInterrupt:
        logger.info("🛑 تم إيقاف البوت بواسطة المستخدم")
    finally:
        logger.info("🧹 جاري تنظيف الموارد...")
        await task_manager.cancel_all()
        await db_pool.close()
        logger.info("✅ تم تنظيف الموارد بنجاح")

if __name__ == "__main__":
    try:
        os.environ["WEB_CONCURRENCY"] = "1"
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 تم إيقاف البوت")
    except Exception as e:
        logger.error(f"❌ خطأ فادح: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
