#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ريلاكس مانيجر - بوت متكامل لإدارة القنوات والمجموعات
الإصدار: 19.3.3 - إضافة أزرار حذف الفيديوهات ورسائل الخدمة والملفات
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
    text = text.replace('\ufeff', '').replace('\ufffc', '')
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
    
    # الأزرار الجديدة لحذف الفيديوهات ورسائل الخدمة والملفات
    SECURITY_DELETE_VIDEOS_PREFIX = "security:delete_videos:"
    SECURITY_DELETE_SERVICE_PREFIX = "security:delete_service:"
    SECURITY_DELETE_DOCUMENTS_PREFIX = "security:delete_documents:"
    
    # ===== إضافة جديدة: زر حذف الملصقات (الاستيكرات) =====
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

# ===================== واجهة الويب المحسّنة (مع دعم Render) =====================

# ===== تكوين Jinja2 =====
template_env = None
if JINJA2_AVAILABLE:
    try:
        template_loader = jinja2.FileSystemLoader(str(TEMPLATES_PATH))
        template_env = jinja2.Environment(loader=template_loader, autoescape=True)
        print("✅ تم تحميل Jinja2 بنجاح")
    except Exception as e:
        print(f"⚠️ فشل تحميل Jinja2: {e}")
        JINJA2_AVAILABLE = False
else:
    print("⚠️ Jinja2 غير متاح - سيتم استخدام HTML النقي")

# ===== إنشاء ملفات HTML =====
def create_web_templates():
    """إنشاء ملفات HTML لواجهة الويب (متوافق مع Render)"""

    index_html = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ريلاكس مانيجر - لوحة التحكم</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --primary: #2d3436;
            --secondary: #0984e3;
            --success: #00b894;
            --danger: #e17055;
            --warning: #fdcb6e;
            --info: #00cec9;
            --dark: #2d3436;
            --light: #dfe6e9;
        }
        [data-theme="dark"] {
            --primary: #dfe6e9;
            --dark: #1a1a2e;
            --light: #2d3436;
        }
        body {
            background: #f5f6fa;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            transition: background 0.3s, color 0.3s;
        }
        [data-theme="dark"] body {
            background: #1a1a2e;
            color: #dfe6e9;
        }
        .sidebar {
            min-height: 100vh;
            background: var(--dark);
            color: white;
            padding: 20px;
            position: fixed;
            right: 0;
            top: 0;
            width: 250px;
            z-index: 1000;
            overflow-y: auto;
            box-shadow: -2px 0 10px rgba(0,0,0,0.1);
            transition: background 0.3s;
        }
        .sidebar .brand {
            font-size: 24px;
            font-weight: bold;
            padding: 20px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            margin-bottom: 20px;
            color: #fff;
        }
        .sidebar .brand i {
            color: var(--secondary);
        }
        .sidebar .nav-link {
            color: rgba(255,255,255,0.7);
            padding: 12px 15px;
            border-radius: 10px;
            margin-bottom: 5px;
            transition: all 0.3s;
        }
        .sidebar .nav-link:hover {
            background: rgba(255,255,255,0.1);
            color: white;
        }
        .sidebar .nav-link.active {
            background: var(--secondary);
            color: white;
        }
        .sidebar .nav-link i {
            margin-left: 10px;
            width: 20px;
            text-align: center;
        }
        .main-content {
            margin-right: 250px;
            padding: 20px;
            min-height: 100vh;
        }
        .stat-card {
            background: white;
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
            transition: all 0.3s;
            border-right: 4px solid var(--secondary);
        }
        [data-theme="dark"] .stat-card {
            background: #2d3436;
            color: #dfe6e9;
        }
        .stat-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 5px 20px rgba(0,0,0,0.1);
        }
        .stat-card .stat-icon {
            font-size: 32px;
            margin-bottom: 10px;
        }
        .stat-card .stat-number {
            font-size: 28px;
            font-weight: bold;
        }
        .stat-card .stat-label {
            color: #636e72;
            font-size: 14px;
        }
        [data-theme="dark"] .stat-card .stat-label {
            color: #b2bec3;
        }
        .stat-card.primary { border-right-color: var(--secondary); }
        .stat-card.success { border-right-color: var(--success); }
        .stat-card.danger { border-right-color: var(--danger); }
        .stat-card.warning { border-right-color: var(--warning); }
        .stat-card.info { border-right-color: var(--info); }
        .card {
            border-radius: 15px;
            border: none;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }
        [data-theme="dark"] .card {
            background: #2d3436;
            color: #dfe6e9;
        }
        .card-header {
            background: white;
            border-bottom: 1px solid #ecf0f1;
            border-radius: 15px 15px 0 0 !important;
            padding: 15px 20px;
            font-weight: bold;
        }
        [data-theme="dark"] .card-header {
            background: #2d3436;
            border-bottom-color: #3d3d4e;
        }
        .table {
            font-size: 14px;
        }
        [data-theme="dark"] .table {
            color: #dfe6e9;
        }
        .table th {
            border-top: none;
            color: #636e72;
            font-weight: 600;
        }
        [data-theme="dark"] .table th {
            color: #b2bec3;
        }
        .status-badge {
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
        }
        .status-badge.active { background: #d4edda; color: #155724; }
        .status-badge.banned { background: #f8d7da; color: #721c24; }
        .status-badge.pending { background: #fff3cd; color: #856404; }
        .status-badge.success { background: #d4edda; color: #155724; }
        .status-badge.danger { background: #f8d7da; color: #721c24; }
        .status-badge.warning { background: #fff3cd; color: #856404; }
        [data-theme="dark"] .status-badge.active { background: #1a3a2a; color: #00b894; }
        [data-theme="dark"] .status-badge.banned { background: #3a1a1a; color: #e17055; }
        [data-theme="dark"] .status-badge.pending { background: #3a3a1a; color: #fdcb6e; }
        .loading-spinner {
            display: none;
            text-align: center;
            padding: 20px;
        }
        .toast-container {
            position: fixed;
            bottom: 20px;
            left: 20px;
            z-index: 9999;
        }
        .profile-img {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: var(--secondary);
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
        }
        .webhook-status {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 5px;
        }
        .webhook-status.online { background: #00b894; }
        .webhook-status.offline { background: #e17055; }
        .theme-toggle {
            cursor: pointer;
            padding: 8px;
            border-radius: 50%;
            background: rgba(255,255,255,0.1);
            transition: all 0.3s;
        }
        .theme-toggle:hover {
            background: rgba(255,255,255,0.2);
        }
        .export-btn {
            cursor: pointer;
            padding: 5px 15px;
            border-radius: 20px;
            background: var(--secondary);
            color: white;
            border: none;
            font-size: 12px;
            transition: all 0.3s;
        }
        .export-btn:hover {
            opacity: 0.8;
        }
        .chart-container {
            position: relative;
            height: 300px;
            margin: 20px 0;
        }
        @media (max-width: 768px) {
            .sidebar {
                position: static;
                width: 100%;
                min-height: auto;
                padding: 10px;
            }
            .main-content {
                margin-right: 0;
                padding: 10px;
            }
        }
        .render-badge {
            position: fixed;
            bottom: 10px;
            right: 260px;
            background: rgba(0,0,0,0.7);
            color: white;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 12px;
            z-index: 999;
        }
        [data-theme="dark"] .render-badge {
            background: rgba(255,255,255,0.1);
        }
    </style>
</head>
<body>
<div class="render-badge">🚀 ريلاكس مانيجر v19.3.3</div>
<div class="sidebar">
    <div class="brand text-center">
        <i class="bi bi-robot"></i> ريلاكس مانيجر
    </div>
    <nav class="nav flex-column">
        <a class="nav-link active" href="#" data-page="dashboard">
            <i class="bi bi-speedometer2"></i> لوحة التحكم
        </a>
        <a class="nav-link" href="#" data-page="users">
            <i class="bi bi-people"></i> المستخدمين
        </a>
        <a class="nav-link" href="#" data-page="channels">
            <i class="bi bi-broadcast"></i> القنوات
        </a>
        <a class="nav-link" href="#" data-page="groups">
            <i class="bi bi-chat-dots"></i> المجموعات
        </a>
        <a class="nav-link" href="#" data-page="posts">
            <i class="bi bi-file-post"></i> المنشورات
        </a>
        <a class="nav-link" href="#" data-page="contests">
            <i class="bi bi-trophy"></i> المسابقات
        </a>
        <a class="nav-link" href="#" data-page="logs">
            <i class="bi bi-journal-text"></i> السجلات
        </a>
        <a class="nav-link" href="#" data-page="backups">
            <i class="bi bi-archive"></i> النسخ الاحتياطية
        </a>
        <a class="nav-link" href="#" data-page="settings">
            <i class="bi bi-gear"></i> الإعدادات
        </a>
        <hr class="border-secondary">
        <div class="d-flex justify-content-between align-items-center px-3 py-2">
            <span class="text-light small">🌙 الوضع</span>
            <span class="theme-toggle" onclick="toggleTheme()">
                <i class="bi bi-moon-fill" id="theme-icon"></i>
            </span>
        </div>
        <a class="nav-link text-danger" href="#" onclick="logout()">
            <i class="bi bi-box-arrow-left"></i> تسجيل الخروج
        </a>
    </nav>
</div>
<div class="main-content">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2 id="page-title">لوحة التحكم</h2>
        <div class="d-flex align-items-center">
            <button class="btn btn-sm btn-outline-primary me-2" onclick="exportData()">
                <i class="bi bi-download"></i> تصدير
            </button>
            <span class="me-3">
                <span class="webhook-status online" id="ws-status"></span>
                <span id="ws-status-text">متصل</span>
            </span>
            <div class="profile-img" id="user-profile">A</div>
        </div>
    </div>
    <div class="loading-spinner" id="loading-spinner">
        <div class="spinner-border text-primary" role="status">
            <span class="visually-hidden">جاري التحميل...</span>
        </div>
        <p class="mt-2">جاري تحميل البيانات...</p>
    </div>
    <div id="page-dashboard" class="page-content">
        <div class="row" id="stats-cards">
            <div class="col-md-3">
                <div class="stat-card primary">
                    <div class="stat-icon"><i class="bi bi-people text-primary"></i></div>
                    <div class="stat-number" id="stat-users">0</div>
                    <div class="stat-label">المستخدمين</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-card success">
                    <div class="stat-icon"><i class="bi bi-broadcast text-success"></i></div>
                    <div class="stat-number" id="stat-channels">0</div>
                    <div class="stat-label">القنوات</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-card warning">
                    <div class="stat-icon"><i class="bi bi-chat-dots text-warning"></i></div>
                    <div class="stat-number" id="stat-groups">0</div>
                    <div class="stat-label">المجموعات</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-card danger">
                    <div class="stat-icon"><i class="bi bi-file-post text-danger"></i></div>
                    <div class="stat-number" id="stat-posts">0</div>
                    <div class="stat-label">منشورات غير منشورة</div>
                </div>
            </div>
        </div>
        <div class="row">
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header">
                        <i class="bi bi-graph-up me-2"></i>نمو المستخدمين
                    </div>
                    <div class="card-body">
                        <div class="chart-container">
                            <canvas id="userGrowthChart"></canvas>
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header">
                        <i class="bi bi-pie-chart me-2"></i>توزيع المنشورات
                    </div>
                    <div class="card-body">
                        <div class="chart-container">
                            <canvas id="postsDistributionChart"></canvas>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        <div class="row">
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header">
                        <i class="bi bi-info-circle me-2"></i>معلومات النظام
                    </div>
                    <div class="card-body" id="system-info">
                        <div class="d-flex justify-content-between border-bottom py-2">
                            <span>حالة البوت</span>
                            <span class="status-badge success">🟢 يعمل</span>
                        </div>
                        <div class="d-flex justify-content-between border-bottom py-2">
                            <span>الإصدار</span>
                            <span>19.3.3</span>
                        </div>
                        <div class="d-flex justify-content-between border-bottom py-2">
                            <span>وقت التشغيل</span>
                            <span id="uptime">0 ساعة</span>
                        </div>
                        <div class="d-flex justify-content-between border-bottom py-2">
                            <span>استخدام الذاكرة</span>
                            <span id="memory-usage">0%</span>
                        </div>
                        <div class="d-flex justify-content-between py-2">
                            <span>قاعدة البيانات</span>
                            <span class="status-badge success" id="db-status">✅ سليمة</span>
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header">
                        <i class="bi bi-activity me-2"></i>النشاطات الأخيرة
                    </div>
                    <div class="card-body" id="recent-activity">
                        <div class="text-muted">لا توجد نشاطات حديثة</div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <div id="page-users" class="page-content" style="display:none;">
        <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
                <span><i class="bi bi-people me-2"></i>قائمة المستخدمين</span>
                <div>
                    <input type="text" class="form-control form-control-sm" id="user-search" placeholder="بحث..." style="width:200px;display:inline-block;">
                    <button class="btn btn-sm btn-primary" onclick="refreshUsers()"><i class="bi bi-arrow-clockwise"></i></button>
                    <button class="btn btn-sm btn-success" onclick="exportData('users')"><i class="bi bi-download"></i></button>
                </div>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-hover" id="users-table">
                        <thead>
                            <tr><th>#</th><th>المعرف</th><th>الاسم</th><th>الحالة</th><th>النقاط</th><th>المستوى</th><th>الإجراءات</th></tr>
                        </thead>
                        <tbody id="users-tbody">
                            <tr><td colspan="7" class="text-center text-muted">جاري التحميل...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    <div id="page-channels" class="page-content" style="display:none;">
        <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
                <span><i class="bi bi-broadcast me-2"></i>قنوات المستخدمين</span>
                <button class="btn btn-sm btn-primary" onclick="refreshChannels()"><i class="bi bi-arrow-clockwise"></i> تحديث</button>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-hover" id="channels-table">
                        <thead>
                            <tr><th>#</th><th>المستخدم</th><th>القناة</th><th>الاسم</th><th>الحالة</th></tr>
                        </thead>
                        <tbody id="channels-tbody">
                            <tr><td colspan="5" class="text-center text-muted">جاري التحميل...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    <div id="page-groups" class="page-content" style="display:none;">
        <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
                <span><i class="bi bi-chat-dots me-2"></i>المجموعات</span>
                <button class="btn btn-sm btn-primary" onclick="refreshGroups()"><i class="bi bi-arrow-clockwise"></i> تحديث</button>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-hover" id="groups-table">
                        <thead>
                            <tr><th>#</th><th>المعرف</th><th>الاسم</th><th>المستخدم</th><th>الحالة</th></tr>
                        </thead>
                        <tbody id="groups-tbody">
                            <tr><td colspan="5" class="text-center text-muted">جاري التحميل...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    <div id="page-posts" class="page-content" style="display:none;">
        <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
                <span><i class="bi bi-file-post me-2"></i>المنشورات غير المنشورة</span>
                <button class="btn btn-sm btn-primary" onclick="refreshPosts()"><i class="bi bi-arrow-clockwise"></i> تحديث</button>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-hover" id="posts-table">
                        <thead>
                            <tr><th>#</th><th>القناة</th><th>النص</th><th>النوع</th><th>التاريخ</th></tr>
                        </thead>
                        <tbody id="posts-tbody">
                            <tr><td colspan="5" class="text-center text-muted">جاري التحميل...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    <div id="page-contests" class="page-content" style="display:none;">
        <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
                <span><i class="bi bi-trophy me-2"></i>المسابقات</span>
                <button class="btn btn-sm btn-primary" onclick="refreshContests()"><i class="bi bi-arrow-clockwise"></i> تحديث</button>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-hover" id="contests-table">
                        <thead>
                            <tr><th>#</th><th>العنوان</th><th>الجائزة</th><th>المشاركون</th><th>التاريخ</th><th>الحالة</th></tr>
                        </thead>
                        <tbody id="contests-tbody">
                            <tr><td colspan="6" class="text-center text-muted">جاري التحميل...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    <div id="page-logs" class="page-content" style="display:none;">
        <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
                <span><i class="bi bi-journal-text me-2"></i>سجلات النظام</span>
                <div>
                    <button class="btn btn-sm btn-primary" onclick="refreshLogs()"><i class="bi bi-arrow-clockwise"></i> تحديث</button>
                    <button class="btn btn-sm btn-danger" onclick="clearLogs()"><i class="bi bi-trash"></i> مسح</button>
                </div>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-hover" id="logs-table">
                        <thead>
                            <tr><th>الوقت</th><th>المستوى</th><th>الرسالة</th></tr>
                        </thead>
                        <tbody id="logs-tbody">
                            <tr><td colspan="3" class="text-center text-muted">جاري التحميل...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    <div id="page-backups" class="page-content" style="display:none;">
        <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
                <span><i class="bi bi-archive me-2"></i>النسخ الاحتياطية</span>
                <div>
                    <button class="btn btn-sm btn-success" onclick="createBackup()"><i class="bi bi-plus"></i> نسخة جديدة</button>
                    <button class="btn btn-sm btn-primary" onclick="refreshBackups()"><i class="bi bi-arrow-clockwise"></i> تحديث</button>
                </div>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-hover" id="backups-table">
                        <thead>
                            <tr><th>#</th><th>الملف</th><th>الحجم</th><th>التاريخ</th><th>الإجراءات</th></tr>
                        </thead>
                        <tbody id="backups-tbody">
                            <tr><td colspan="5" class="text-center text-muted">جاري التحميل...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    <div id="page-settings" class="page-content" style="display:none;">
        <div class="card">
            <div class="card-header">
                <i class="bi bi-gear me-2"></i>إعدادات البوت
            </div>
            <div class="card-body">
                <form id="settings-form">
                    <div class="row">
                        <div class="col-md-6">
                            <div class="mb-3">
                                <label class="form-label">اسم البوت</label>
                                <input type="text" class="form-control" id="setting-bot-name" value="ريلاكس مانيجر">
                            </div>
                            <div class="mb-3">
                                <label class="form-label">معرف البوت</label>
                                <input type="text" class="form-control" id="setting-bot-username" value="Reelaaaxbot">
                            </div>
                            <div class="mb-3">
                                <label class="form-label">وقت النشر (ثانية)</label>
                                <input type="number" class="form-control" id="setting-publish-interval" value="720">
                            </div>
                        </div>
                        <div class="col-md-6">
                            <div class="mb-3">
                                <label class="form-label">قناة التحديثات</label>
                                <input type="text" class="form-control" id="setting-updates-channel" placeholder="@channel">
                            </div>
                            <div class="mb-3">
                                <div class="form-check form-switch">
                                    <input class="form-check-input" type="checkbox" id="setting-force-subscribe">
                                    <label class="form-check-label">الاشتراك الإجباري</label>
                                </div>
                            </div>
                            <div class="mb-3">
                                <div class="form-check form-switch">
                                    <input class="form-check-input" type="checkbox" id="setting-auto-backup">
                                    <label class="form-check-label">النسخ الاحتياطي التلقائي</label>
                                </div>
                            </div>
                            <div class="mb-3">
                                <div class="form-check form-switch">
                                    <input class="form-check-input" type="checkbox" id="setting-nsfw">
                                    <label class="form-check-label">كشف NSFW</label>
                                </div>
                            </div>
                        </div>
                    </div>
                    <button type="submit" class="btn btn-primary">حفظ الإعدادات</button>
                </form>
            </div>
        </div>
    </div>
</div>
<div class="toast-container">
    <div id="liveToast" class="toast" role="alert" aria-live="assertive" aria-atomic="true">
        <div class="toast-header">
            <strong class="me-auto"><i class="bi bi-bell"></i> إشعار</strong>
            <button type="button" class="btn-close" data-bs-dismiss="toast"></button>
        </div>
        <div class="toast-body" id="toast-body">رسالة</div>
    </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
let currentTheme = localStorage.getItem('theme') || 'light';
function toggleTheme() {
    currentTheme = currentTheme === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', currentTheme);
    localStorage.setItem('theme', currentTheme);
    document.getElementById('theme-icon').className = currentTheme === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
}
document.addEventListener('DOMContentLoaded', function() {
    document.documentElement.setAttribute('data-theme', currentTheme);
    document.getElementById('theme-icon').className = currentTheme === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
});
function exportData(type) {
    let url = '/api/export';
    if (type) { url += '?type=' + type; }
    window.location.href = url;
}
let ws = null;
let wsReconnectAttempts = 0;
const MAX_WS_RECONNECT = 5;
function connectWebSocket() {
    const token = '{{ WEB_SECRET_KEY }}';
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws_extended?token=${encodeURIComponent(token)}`;
    ws = new WebSocket(wsUrl);
    ws.onopen = function() {
        console.log('✅ WebSocket متصل');
        document.getElementById('ws-status').className = 'webhook-status online';
        document.getElementById('ws-status-text').textContent = 'متصل';
        wsReconnectAttempts = 0;
    };
    ws.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            handleWebSocketMessage(data);
        } catch(e) {
            console.error('خطأ في تحليل رسالة WebSocket:', e);
        }
    };
    ws.onclose = function() {
        console.log('❌ WebSocket مغلق');
        document.getElementById('ws-status').className = 'webhook-status offline';
        document.getElementById('ws-status-text').textContent = 'غير متصل';
        if (wsReconnectAttempts < MAX_WS_RECONNECT) {
            wsReconnectAttempts++;
            setTimeout(connectWebSocket, 3000 * wsReconnectAttempts);
        }
    };
    ws.onerror = function(error) {
        console.error('خطأ في WebSocket:', error);
    };
}
function handleWebSocketMessage(data) {
    switch(data.type) {
        case 'stats': updateStats(data.data); break;
        case 'broadcast': showToast(data.data.message || 'تم استلام تحديث جديد'); break;
        case 'pong': break;
        default: console.log('رسالة غير معروفة:', data);
    }
}
function showToast(message, type = 'info') {
    const toast = document.getElementById('liveToast');
    const body = document.getElementById('toast-body');
    body.textContent = message;
    const bsToast = new bootstrap.Toast(toast, { delay: 3000 });
    bsToast.show();
}
function updateStats(data) {
    document.getElementById('stat-users').textContent = data.total_users || 0;
    document.getElementById('stat-channels').textContent = data.channels || 0;
    document.getElementById('stat-groups').textContent = data.groups || 0;
    document.getElementById('stat-posts').textContent = data.pending_posts || 0;
}
let userGrowthChart = null;
let postsDistributionChart = null;
function initCharts() {
    const ctx1 = document.getElementById('userGrowthChart').getContext('2d');
    userGrowthChart = new Chart(ctx1, {
        type: 'line',
        data: { labels: [], datasets: [{ label: 'المستخدمين', data: [], borderColor: '#0984e3', backgroundColor: 'rgba(9, 132, 227, 0.1)', fill: true, tension: 0.4 }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: currentTheme === 'dark' ? '#dfe6e9' : '#2d3436' } } }, scales: { y: { beginAtZero: true, ticks: { color: currentTheme === 'dark' ? '#dfe6e9' : '#2d3436' } }, x: { ticks: { color: currentTheme === 'dark' ? '#dfe6e9' : '#2d3436' } } } }
    });
    const ctx2 = document.getElementById('postsDistributionChart').getContext('2d');
    postsDistributionChart = new Chart(ctx2, {
        type: 'doughnut',
        data: { labels: ['منشورة', 'غير منشورة'], datasets: [{ data: [0, 0], backgroundColor: ['#00b894', '#e17055'], borderWidth: 2, borderColor: currentTheme === 'dark' ? '#2d3436' : '#ffffff' }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: currentTheme === 'dark' ? '#dfe6e9' : '#2d3436' } } } }
    });
}
function updateCharts(userGrowth, postsDistribution) {
    if (userGrowthChart) {
        userGrowthChart.data.labels = userGrowth.labels || [];
        userGrowthChart.data.datasets[0].data = userGrowth.data || [];
        userGrowthChart.update();
    }
    if (postsDistributionChart) {
        postsDistributionChart.data.datasets[0].data = [postsDistribution.published || 0, postsDistribution.unpublished || 0];
        postsDistributionChart.update();
    }
}
document.querySelectorAll('.sidebar .nav-link').forEach(link => {
    link.addEventListener('click', function(e) {
        e.preventDefault();
        document.querySelectorAll('.sidebar .nav-link').forEach(l => l.classList.remove('active'));
        this.classList.add('active');
        const page = this.dataset.page;
        document.querySelectorAll('.page-content').forEach(p => p.style.display = 'none');
        const targetPage = document.getElementById(`page-${page}`);
        if (targetPage) {
            targetPage.style.display = 'block';
            document.getElementById('page-title').textContent = this.textContent.trim();
            switch(page) {
                case 'dashboard': refreshDashboard(); break;
                case 'users': refreshUsers(); break;
                case 'channels': refreshChannels(); break;
                case 'groups': refreshGroups(); break;
                case 'posts': refreshPosts(); break;
                case 'contests': refreshContests(); break;
                case 'logs': refreshLogs(); break;
                case 'backups': refreshBackups(); break;
                case 'settings': loadSettings(); break;
            }
        }
    });
});
function refreshDashboard() {
    fetch('/api/stats').then(res => res.json()).then(data => { updateStats(data); fetch('/api/charts').then(res => res.json()).then(chartData => { updateCharts(chartData.user_growth, chartData.posts_distribution); }).catch(err => console.error('خطأ في تحميل الرسوم البيانية:', err)); }).catch(err => console.error('خطأ في تحميل الإحصائيات:', err));
    fetch('/api/system-info').then(res => res.json()).then(data => { document.getElementById('uptime').textContent = data.uptime || '0 ساعة'; document.getElementById('memory-usage').textContent = data.memory || '0%'; }).catch(err => console.error('خطأ في تحميل معلومات النظام:', err));
}
function refreshUsers() {
    const tbody = document.getElementById('users-tbody');
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">جاري التحميل...</td></tr>';
    fetch('/api/users').then(res => res.json()).then(data => {
        if (!data || data.length === 0) { tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">لا يوجد مستخدمين</td></tr>'; return; }
        tbody.innerHTML = data.map((user, i) => `<tr><td>${i+1}</td><td><code>${user.user_id}</code></td><td>${user.first_name || 'غير معروف'}</td><td><span class="status-badge ${user.banned ? 'danger' : 'success'}">${user.banned ? '🚫 محظور' : '✅ نشط'}</span></td><td>${user.points || 0}</td><td>${user.level || 1}</td><td><button class="btn btn-sm btn-${user.banned ? 'success' : 'danger'}" onclick="toggleBan(${user.user_id})">${user.banned ? '🔓 إلغاء الحظر' : '🚫 حظر'}</button></td></tr>`).join('');
    }).catch(err => { console.error('خطأ في تحميل المستخدمين:', err); tbody.innerHTML = '<tr><td colspan="7" class="text-center text-danger">❌ فشل التحميل</td></tr>'; });
}
function toggleBan(userId) {
    fetch(`/api/users/${userId}/toggle-ban`, { method: 'POST' }).then(res => res.json()).then(data => { showToast(data.message || 'تم تغيير الحالة'); refreshUsers(); }).catch(err => showToast('❌ فشل تغيير الحالة', 'error'));
}
function refreshChannels() {
    const tbody = document.getElementById('channels-tbody');
    tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">جاري التحميل...</td></tr>';
    fetch('/api/channels').then(res => res.json()).then(data => {
        if (!data || data.length === 0) { tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">لا توجد قنوات</td></tr>'; return; }
        tbody.innerHTML = data.map((ch, i) => `<tr><td>${i+1}</td><td><code>${ch.user_id}</code></td><td><code>${ch.channel_id}</code></td><td>${ch.channel_name || ch.channel_id}</td><td><span class="status-badge ${ch.banned ? 'danger' : 'success'}">${ch.banned ? '⛔ محظورة' : '✅ نشطة'}</span></td></tr>`).join('');
    }).catch(err => { console.error('خطأ في تحميل القنوات:', err); tbody.innerHTML = '<tr><td colspan="5" class="text-center text-danger">❌ فشل التحميل</td></tr>'; });
}
function refreshGroups() {
    const tbody = document.getElementById('groups-tbody');
    tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">جاري التحميل...</td></tr>';
    fetch('/api/groups').then(res => res.json()).then(data => {
        if (!data || data.length === 0) { tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">لا توجد مجموعات</td></tr>'; return; }
        tbody.innerHTML = data.map((g, i) => `<tr><td>${i+1}</td><td><code>${g.chat_id}</code></td><td>${g.chat_name || g.chat_id}</td><td><code>${g.added_by}</code></td><td><span class="status-badge ${g.banned ? 'danger' : 'success'}">${g.banned ? '⛔ محظورة' : '✅ نشطة'}</span></td></tr>`).join('');
    }).catch(err => { console.error('خطأ في تحميل المجموعات:', err); tbody.innerHTML = '<tr><td colspan="5" class="text-center text-danger">❌ فشل التحميل</td></tr>'; });
}
function refreshPosts() {
    const tbody = document.getElementById('posts-tbody');
    tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">جاري التحميل...</td></tr>';
    fetch('/api/posts').then(res => res.json()).then(data => {
        if (!data || data.length === 0) { tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">لا توجد منشورات غير منشورة</td></tr>'; return; }
        tbody.innerHTML = data.map((p, i) => `<tr><td>${i+1}</td><td>${p.channel_name || p.channel_id}</td><td>${(p.text || '').substring(0, 50)}${(p.text || '').length > 50 ? '...' : ''}</td><td><span class="badge bg-secondary">${p.media_type || 'text'}</span></td><td>${p.created_at ? new Date(p.created_at).toLocaleDateString('ar-EG') : '-'}</td></tr>`).join('');
    }).catch(err => { console.error('خطأ في تحميل المنشورات:', err); tbody.innerHTML = '<tr><td colspan="5" class="text-center text-danger">❌ فشل التحميل</td></tr>'; });
}
function refreshContests() {
    const tbody = document.getElementById('contests-tbody');
    tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">جاري التحميل...</td></tr>';
    fetch('/api/contests').then(res => res.json()).then(data => {
        if (!data || data.length === 0) { tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">لا توجد مسابقات</td></tr>'; return; }
        tbody.innerHTML = data.map((c, i) => `<tr><td>${i+1}</td><td>${c.title || 'بدون عنوان'}</td><td>${c.prize || 'غير محددة'}</td><td>${c.participants || 0}</td><td>${c.end_date ? new Date(c.end_date).toLocaleDateString('ar-EG') : '-'}</td><td><span class="status-badge ${c.status === 'active' ? 'success' : 'secondary'}">${c.status === 'active' ? 'نشطة' : 'منتهية'}</span></td></tr>`).join('');
    }).catch(err => { console.error('خطأ في تحميل المسابقات:', err); tbody.innerHTML = '<tr><td colspan="6" class="text-center text-danger">❌ فشل التحميل</td></tr>'; });
}
function refreshLogs() {
    const tbody = document.getElementById('logs-tbody');
    tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">جاري التحميل...</td></tr>';
    fetch('/api/logs').then(res => res.json()).then(data => {
        if (!data || data.length === 0) { tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">لا توجد سجلات</td></tr>'; return; }
        tbody.innerHTML = data.map(log => { const level = log.level || 'INFO'; const levelClass = { 'ERROR': 'danger', 'WARNING': 'warning', 'INFO': 'info', 'DEBUG': 'secondary' }[level] || 'info'; return `<tr><td>${log.time || '-'}</td><td><span class="badge bg-${levelClass}">${level}</span></td><td>${log.message || ''}</td></tr>`; }).join('');
    }).catch(err => { console.error('خطأ في تحميل السجلات:', err); tbody.innerHTML = '<tr><td colspan="3" class="text-center text-danger">❌ فشل التحميل</td></tr>'; });
}
function clearLogs() {
    if (!confirm('هل أنت متأكد من مسح جميع السجلات؟')) return;
    fetch('/api/logs', { method: 'DELETE' }).then(res => res.json()).then(data => { showToast(data.message || 'تم مسح السجلات'); refreshLogs(); }).catch(err => showToast('❌ فشل مسح السجلات', 'error'));
}
function refreshBackups() {
    const tbody = document.getElementById('backups-tbody');
    tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">جاري التحميل...</td></tr>';
    fetch('/api/backups').then(res => res.json()).then(data => {
        if (!data || data.length === 0) { tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">لا توجد نسخ احتياطية</td></tr>'; return; }
        tbody.innerHTML = data.map((b, i) => `<tr><td>${i+1}</td><td>${b.name || 'غير معروف'}</td><td>${b.size ? (b.size / 1024).toFixed(2) + ' KB' : '-'}</td><td>${b.date || '-'}</td><td><button class="btn btn-sm btn-success" onclick="restoreBackup('${b.name}')"><i class="bi bi-arrow-counterclockwise"></i> استعادة</button> <button class="btn btn-sm btn-danger" onclick="deleteBackup('${b.name}')"><i class="bi bi-trash"></i> حذف</button></td></tr>`).join('');
    }).catch(err => { console.error('خطأ في تحميل النسخ الاحتياطية:', err); tbody.innerHTML = '<tr><td colspan="5" class="text-center text-danger">❌ فشل التحميل</td></tr>'; });
}
function createBackup() {
    fetch('/api/backups', { method: 'POST' }).then(res => res.json()).then(data => { showToast(data.message || '✅ تم إنشاء نسخة احتياطية'); refreshBackups(); }).catch(err => showToast('❌ فشل إنشاء النسخة', 'error'));
}
function restoreBackup(name) {
    if (!confirm(`هل أنت متأكد من استعادة النسخة ${name}؟`)) return;
    fetch(`/api/backups/${encodeURIComponent(name)}/restore`, { method: 'POST' }).then(res => res.json()).then(data => { showToast(data.message || '✅ تم استعادة النسخة'); refreshBackups(); }).catch(err => showToast('❌ فشل استعادة النسخة', 'error'));
}
function deleteBackup(name) {
    if (!confirm(`هل أنت متأكد من حذف النسخة ${name}؟`)) return;
    fetch(`/api/backups/${encodeURIComponent(name)}`, { method: 'DELETE' }).then(res => res.json()).then(data => { showToast(data.message || '✅ تم حذف النسخة'); refreshBackups(); }).catch(err => showToast('❌ فشل حذف النسخة', 'error'));
}
function loadSettings() {
    fetch('/api/settings').then(res => res.json()).then(data => {
        if (data.bot_name) document.getElementById('setting-bot-name').value = data.bot_name;
        if (data.bot_username) document.getElementById('setting-bot-username').value = data.bot_username;
        if (data.publish_interval) document.getElementById('setting-publish-interval').value = data.publish_interval;
        if (data.updates_channel) document.getElementById('setting-updates-channel').value = data.updates_channel;
        document.getElementById('setting-force-subscribe').checked = data.force_subscribe || false;
        document.getElementById('setting-auto-backup').checked = data.auto_backup || false;
        document.getElementById('setting-nsfw').checked = data.nsfw_enabled || false;
    }).catch(err => console.error('خطأ في تحميل الإعدادات:', err));
}
document.getElementById('settings-form').addEventListener('submit', function(e) {
    e.preventDefault();
    const data = {
        bot_name: document.getElementById('setting-bot-name').value,
        bot_username: document.getElementById('setting-bot-username').value,
        publish_interval: parseInt(document.getElementById('setting-publish-interval').value) || 720,
        updates_channel: document.getElementById('setting-updates-channel').value,
        force_subscribe: document.getElementById('setting-force-subscribe').checked,
        auto_backup: document.getElementById('setting-auto-backup').checked,
        nsfw_enabled: document.getElementById('setting-nsfw').checked
    };
    fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then(res => res.json()).then(data => { showToast(data.message || '✅ تم حفظ الإعدادات'); }).catch(err => showToast('❌ فشل حفظ الإعدادات', 'error'));
});
function logout() {
    if (confirm('هل أنت متأكد من تسجيل الخروج؟')) {
        document.cookie = 'session_id=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
        window.location.href = '/logout';
    }
}
document.getElementById('user-search').addEventListener('input', function() {
    const query = this.value.toLowerCase();
    const rows = document.querySelectorAll('#users-tbody tr');
    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(query) ? '' : 'none';
    });
});
setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }));
    }
}, 30000);
setInterval(() => {
    const activePage = document.querySelector('.sidebar .nav-link.active');
    if (activePage) {
        const page = activePage.dataset.page;
        switch(page) {
            case 'dashboard': refreshDashboard(); break;
            case 'users': refreshUsers(); break;
            case 'channels': refreshChannels(); break;
            case 'groups': refreshGroups(); break;
            case 'posts': refreshPosts(); break;
            case 'contests': refreshContests(); break;
            case 'logs': refreshLogs(); break;
            case 'backups': refreshBackups(); break;
        }
    }
}, 30000);
document.addEventListener('DOMContentLoaded', function() {
    connectWebSocket();
    initCharts();
    refreshDashboard();
    document.getElementById('page-dashboard').style.display = 'block';
});
</script>
</body>
</html>"""

    try:
        with open(TEMPLATES_PATH / "index.html", "w", encoding="utf-8") as f:
            f.write(index_html)
        logger.info("✅ تم إنشاء قالب HTML لواجهة الويب")
        return True
    except Exception as e:
        logger.error(f"❌ فشل إنشاء قالب HTML: {e}")
        return False

# محاولة إنشاء القوالب
try:
    create_web_templates()
except Exception as e:
    print(f"⚠️ فشل إنشاء قوالب الويب: {e}")

# ===== واجهة الويب =====
web_app = web.Application()
WEB_SESSIONS = {}
WEB_SESSION_TIMEOUT = 3600
WEB_RATE_LIMITS = defaultdict(list)
WEB_RATE_LIMIT = 100
WEB_RATE_WINDOW = 60

def generate_session_id() -> str:
    return secrets.token_urlsafe(32)

def create_session(user_data: dict) -> str:
    session_id = generate_session_id()
    WEB_SESSIONS[session_id] = {
        'user_data': user_data,
        'created_at': time_module.time(),
        'last_activity': time_module.time()
    }
    return session_id

def get_session(session_id: str) -> dict | None:
    if session_id not in WEB_SESSIONS:
        return None
    session = WEB_SESSIONS[session_id]
    if time_module.time() - session['last_activity'] > WEB_SESSION_TIMEOUT:
        del WEB_SESSIONS[session_id]
        return None
    session['last_activity'] = time_module.time()
    return session['user_data']

def delete_session(session_id: str):
    if session_id in WEB_SESSIONS:
        del WEB_SESSIONS[session_id]

def check_rate_limit(ip: str) -> bool:
    now = time_module.time()
    WEB_RATE_LIMITS[ip] = [t for t in WEB_RATE_LIMITS[ip] if now - t < WEB_RATE_WINDOW]
    if len(WEB_RATE_LIMITS[ip]) >= WEB_RATE_LIMIT:
        return False
    WEB_RATE_LIMITS[ip].append(now)
    return True

def check_web_auth(request):
    session_id = request.cookies.get('session_id')
    if session_id:
        session = get_session(session_id)
        if session:
            return True

    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Basic '):
        try:
            encoded = auth_header.split(' ')[1]
            decoded = base64.b64decode(encoded).decode('utf-8')
            username, password = decoded.split(':', 1)
            if username == "admin" and password == "mmmmm739377114":
                return True
        except:
            pass
    return False

@web.middleware
async def auth_middleware(request, handler):
    # السماح للـ API والملفات الثابتة
    if request.path.startswith('/api/') or request.path.startswith('/static/') or request.path in ['/login', '/logout', '/health', '/ws', '/ws_extended']:
        return await handler(request)
    if not check_web_auth(request):
        return web.Response(status=401, text="🔒 مطلوب مصادقة")
    return await handler(request)

web_app.middlewares.append(auth_middleware)

# ===== API Handlers =====
async def api_stats_handler(request):
    try:
        total, banned, posts, groups, channels = await db_stats()
        return web.json_response({
            'total_users': total,
            'active_users': total - banned,
            'banned_users': banned,
            'pending_posts': posts,
            'groups': groups,
            'channels': channels
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_charts_handler(request):
    try:
        user_growth = {'labels': [], 'data': []}
        try:
            async def _get_user_growth(conn):
                cur = await conn.execute("""
                    SELECT date(last_updated) as date, COUNT(*) as count
                    FROM users_cache
                    WHERE last_updated >= datetime('now', '-30 days')
                    GROUP BY date(last_updated)
                    ORDER BY date
                """)
                return await cur.fetchall()
            growth_data = await execute_db(_get_user_growth)
            for row in growth_data:
                user_growth['labels'].append(row[0])
                user_growth['data'].append(row[1])
        except:
            pass

        posts_distribution = {'published': 0, 'unpublished': 0}
        try:
            async def _get_posts_dist(conn):
                cur = await conn.execute("SELECT published, COUNT(*) FROM posts GROUP BY published")
                return await cur.fetchall()
            dist_data = await execute_db(_get_posts_dist)
            for row in dist_data:
                if row[0] == 1:
                    posts_distribution['published'] = row[1]
                else:
                    posts_distribution['unpublished'] = row[1]
        except:
            pass

        return web.json_response({
            'user_growth': user_growth,
            'posts_distribution': posts_distribution
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_export_handler(request):
    try:
        export_type = request.query.get('type', 'all')
        import csv
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8')

        if export_type == 'users' or export_type == 'all':
            users = await db_get_all_users()
            writer = csv.writer(temp_file)
            writer.writerow(['User ID', 'Banned'])
            for user_id, banned in users:
                writer.writerow([user_id, banned])
            temp_file.write('\n')

        if export_type == 'channels' or export_type == 'all':
            channels = await db_get_all_user_channels_no_limit()
            writer = csv.writer(temp_file)
            writer.writerow(['User ID', 'Channel DB ID', 'Channel ID', 'Channel Name', 'Banned'])
            for user_id, ch_id, ch_tele, ch_name, banned in channels:
                writer.writerow([user_id, ch_id, ch_tele, ch_name, banned])
            temp_file.write('\n')

        if export_type == 'groups' or export_type == 'all':
            groups = await db_get_all_groups()
            writer = csv.writer(temp_file)
            writer.writerow(['Chat ID', 'Chat Name', 'Username', 'Added By', 'Added At', 'Banned'])
            for chat_id, chat_name, username, added_by, added_at, banned in groups:
                writer.writerow([chat_id, chat_name, username, added_by, added_at, banned])
            temp_file.write('\n')

        if export_type == 'posts' or export_type == 'all':
            async def _get_posts(conn):
                cur = await conn.execute("SELECT p.id, p.text, p.media_type, p.published, p.created_at, uc.channel_id FROM posts p JOIN user_channels uc ON p.channel_db_id = uc.id LIMIT 1000")
                return await cur.fetchall()
            posts = await execute_db(_get_posts)
            writer = csv.writer(temp_file)
            writer.writerow(['Post ID', 'Text', 'Media Type', 'Published', 'Created At', 'Channel ID'])
            for post in posts:
                writer.writerow([post[0], post[1][:100] if post[1] else '', post[2], post[3], post[4], post[5]])

        temp_file.close()
        with open(temp_file.name, 'rb') as f:
            data = f.read()
        os.unlink(temp_file.name)

        filename = f"export_{export_type}_{mecca_now().strftime('%Y%m%d_%H%M%S')}.csv"
        return web.Response(body=data, headers={
            'Content-Type': 'text/csv',
            'Content-Disposition': f'attachment; filename="{filename}"'
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_users_handler(request):
    try:
        users = await db_get_all_users()
        result = []
        for user_id, banned in users:
            level_data = await db_get_user_level(user_id)
            result.append({
                'user_id': user_id,
                'banned': banned == 1,
                'points': level_data['points'],
                'level': level_data['level'],
                'first_name': 'مستخدم'
            })
        return web.json_response(result)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_user_toggle_ban_handler(request):
    try:
        user_id = int(request.match_info['user_id'])
        users = await db_get_all_users()
        user_exists = any(u[0] == user_id for u in users)
        if not user_exists:
            return web.json_response({'error': 'المستخدم غير موجود'}, status=404)
        current_ban = await db_is_banned(user_id)
        await db_set_ban(user_id, not current_ban)
        return web.json_response({
            'success': True,
            'message': f'تم {"حظر" if not current_ban else "إلغاء حظر"} المستخدم'
        })
    except ValueError:
        return web.json_response({'error': 'معرف غير صالح'}, status=400)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_channels_handler(request):
    try:
        channels = await db_get_all_user_channels_no_limit()
        result = []
        for user_id, ch_id, ch_tele, ch_name, banned in channels:
            result.append({
                'user_id': user_id,
                'channel_id': ch_tele,
                'channel_name': ch_name,
                'banned': banned == 1
            })
        return web.json_response(result)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_groups_handler(request):
    try:
        groups = await db_get_all_groups()
        result = []
        for chat_id, chat_name, username, added_by, added_at, banned in groups:
            result.append({
                'chat_id': chat_id,
                'chat_name': chat_name,
                'username': username,
                'added_by': added_by,
                'added_at': added_at,
                'banned': banned == 1
            })
        return web.json_response(result)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_posts_handler(request):
    try:
        async def _get_posts(conn):
            cur = await conn.execute("""
                SELECT p.id, p.channel_db_id, p.text, p.media_type, p.created_at,
                       uc.channel_id, uc.channel_name
                FROM posts p
                JOIN user_channels uc ON p.channel_db_id = uc.id
                WHERE p.published = 0
                ORDER BY p.created_at DESC
                LIMIT 100
            """)
            return await cur.fetchall()
        posts = await execute_db(_get_posts)
        result = []
        for post in posts:
            result.append({
                'id': post[0],
                'channel_db_id': post[1],
                'text': post[2],
                'media_type': post[3],
                'created_at': post[4],
                'channel_id': post[5],
                'channel_name': post[6]
            })
        return web.json_response(result)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_contests_handler(request):
    try:
        contests = await db_get_active_contests_with_participants(limit=20)
        result = []
        for contest in contests:
            result.append({
                'id': contest[0],
                'title': contest[1],
                'description': contest[2],
                'prize': contest[3],
                'end_date': contest[4],
                'participants': contest[5] if len(contest) > 5 else 0,
                'status': 'active'
            })
        return web.json_response(result)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_logs_handler(request):
    try:
        limit = int(request.query.get('limit', 50))
        logs = []
        if LOG_PATH.exists():
            with open(LOG_PATH, 'r', encoding='utf-8') as f:
                lines = f.readlines()[-limit:]
                for line in lines:
                    try:
                        parts = line.strip().split(' - ', 3)
                        if len(parts) >= 4:
                            logs.append({
                                'time': parts[0],
                                'level': parts[1] if len(parts) > 1 else 'INFO',
                                'message': parts[-1]
                            })
                        else:
                            logs.append({
                                'time': '',
                                'level': 'INFO',
                                'message': line.strip()
                            })
                    except:
                        logs.append({
                            'time': '',
                            'level': 'INFO',
                            'message': line.strip()
                        })
        return web.json_response(logs)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_logs_delete_handler(request):
    try:
        if LOG_PATH.exists():
            with open(LOG_PATH, 'w', encoding='utf-8') as f:
                f.write('')
        return web.json_response({'success': True, 'message': 'تم مسح السجلات'})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_backups_handler(request):
    try:
        backups = await list_backups()
        result = []
        for backup in backups:
            stat = backup.stat()
            result.append({
                'name': backup.name,
                'size': stat.st_size,
                'date': datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
        return web.json_response(result)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_backup_create_handler(request):
    try:
        backup_path = await create_backup()
        return web.json_response({
            'success': True,
            'message': '✅ تم إنشاء نسخة احتياطية',
            'file': backup_path.name
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_backup_restore_handler(request):
    try:
        name = request.match_info['name']
        backup_path = BACKUP_DIR / name
        if not backup_path.exists():
            return web.json_response({'error': 'الملف غير موجود'}, status=404)
        await restore_backup(backup_path)
        return web.json_response({'success': True, 'message': '✅ تم استعادة النسخة'})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_backup_delete_handler(request):
    try:
        name = request.match_info['name']
        backup_path = BACKUP_DIR / name
        if not backup_path.exists():
            return web.json_response({'error': 'الملف غير موجود'}, status=404)
        backup_path.unlink()
        return web.json_response({'success': True, 'message': '✅ تم حذف النسخة'})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_settings_handler(request):
    try:
        publish_interval = await db_get_publish_interval()
        updates_channel = await db_get_updates_channel()
        force_subscribe = await db_get_force_subscribe_status()
        auto_backup = await db_get_auto_backup()
        return web.json_response({
            'bot_name': BOT_NAME,
            'bot_username': BOT_USERNAME,
            'publish_interval': publish_interval,
            'updates_channel': updates_channel or '',
            'force_subscribe': force_subscribe,
            'auto_backup': auto_backup,
            'nsfw_enabled': NSFW_ENABLED
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_settings_update_handler(request):
    try:
        data = await request.json()
        if 'publish_interval' in data:
            seconds = int(data['publish_interval']) * 60
            await db_set_publish_interval_seconds(seconds, PRIMARY_OWNER_ID, is_admin=True)
        if 'updates_channel' in data:
            channel = data['updates_channel'].strip()
            if channel:
                if channel.startswith('@'):
                    channel = channel[1:]
                await db_set_updates_channel(channel)
        if 'force_subscribe' in data:
            await db_set_force_subscribe_status(data['force_subscribe'])
        if 'auto_backup' in data:
            await db_set_auto_backup(data['auto_backup'])
        if 'nsfw_enabled' in data:
            global NSFW_ENABLED
            NSFW_ENABLED = data['nsfw_enabled']
            os.environ["NSFW_ENABLED"] = "True" if NSFW_ENABLED else "False"
        return web.json_response({'success': True, 'message': '✅ تم حفظ الإعدادات'})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_system_info_handler(request):
    try:
        ram = get_ram_usage()
        uptime = time_module.time() - getattr(api_system_info_handler, 'start_time', time_module.time())
        uptime_hours = int(uptime / 3600)
        uptime_minutes = int((uptime % 3600) / 60)
        db_healthy = await check_database_health()
        tg_healthy = await check_telegram_health()
        return web.json_response({
            'uptime': f'{uptime_hours} ساعة {uptime_minutes} دقيقة',
            'memory': f"{ram['percent']}%",
            'db_status': '✅ سليمة' if db_healthy else '❌ تالفة',
            'telegram_status': '✅ متصل' if tg_healthy else '❌ غير متصل',
            'version': '19.3.3',
            'platform': platform.platform()
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

# ===== Web Routes =====
async def root_handler(request):
    if not check_web_auth(request):
        return web.Response(status=401, headers={"WWW-Authenticate": 'Basic realm="البوت"'})
    try:
        if check_web_auth(request):
            session_id = request.cookies.get('session_id')
            if JINJA2_AVAILABLE and template_env:
                try:
                    template = template_env.get_template('index.html')
                    html = template.render(
                        WEB_SECRET_KEY=WEB_SECRET_KEY,
                        BOT_NAME=BOT_NAME,
                        BOT_USERNAME=BOT_USERNAME
                    )
                    return web.Response(text=html, content_type='text/html')
                except Exception as e:
                    logger.error(f"خطأ في عرض القالب: {e}")
            try:
                with open(TEMPLATES_PATH / "index.html", "r", encoding='utf-8') as f:
                    html = f.read()
                    html = html.replace("{{ WEB_SECRET_KEY }}", WEB_SECRET_KEY)
                    html = html.replace("{{ BOT_NAME }}", BOT_NAME)
                    html = html.replace("{{ BOT_USERNAME }}", BOT_USERNAME)
                    return web.Response(text=html, content_type='text/html')
            except:
                return web.Response(text="""<!DOCTYPE html><html><head><title>ريلاكس مانيجر</title></head>
                <body><h1>🚀 ريلاكس مانيجر يعمل!</h1><p>الرجاء تسجيل الدخول</p></body></html>""", content_type='text/html')
        else:
            return web.Response(status=401, headers={'WWW-Authenticate': 'Basic realm="البوت"'})
    except Exception as e:
        logger.error(f"خطأ في عرض الصفحة الرئيسية: {e}")
        return web.Response(text=f"❌ حدث خطأ: {e}", status=500)

async def login_handler(request):
    try:
        if request.method == 'POST':
            data = await request.post()
            username = data.get('username', '')
            password = data.get('password', '')
            if username == "admin" and password == "mmmmm739377114":
                session_id = create_session({'username': username})
                response = web.Response(status=302, headers={'Location': '/'})
                response.set_cookie('session_id', session_id, httponly=True, max_age=WEB_SESSION_TIMEOUT)
                return response
            return web.Response(text='❌ اسم المستخدم أو كلمة المرور غير صحيحة', status=401)
        html = """
        <!DOCTYPE html>
        <html lang="ar" dir="rtl">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>تسجيل الدخول - ريلاكس مانيجر</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body { background: #f5f6fa; display: flex; align-items: center; justify-content: center; min-height: 100vh; }
                .login-card { background: white; border-radius: 20px; padding: 40px; box-shadow: 0 10px 40px rgba(0,0,0,0.1); width: 100%; max-width: 400px; }
                .login-card .brand { font-size: 28px; font-weight: bold; color: #2d3436; margin-bottom: 30px; text-align: center; }
                .login-card .brand i { color: #0984e3; }
            </style>
        </head>
        <body>
            <div class="login-card">
                <div class="brand"><i class="bi bi-robot"></i> ريلاكس مانيجر</div>
                <h5 class="text-center mb-4">🔐 تسجيل الدخول</h5>
                <form method="POST">
                    <div class="mb-3"><label class="form-label">اسم المستخدم</label><input type="text" name="username" class="form-control" required autofocus></div>
                    <div class="mb-3"><label class="form-label">كلمة المرور</label><input type="password" name="password" class="form-control" required></div>
                    <button type="submit" class="btn btn-primary w-100">دخول</button>
                </form>
                <hr><p class="text-center text-muted small">© 2026 ريلاكس مانيجر - الإصدار 19.3.3</p>
            </div>
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
        </body>
        </html>
        """
        return web.Response(text=html, content_type='text/html')
    except Exception as e:
        logger.error(f"خطأ في صفحة تسجيل الدخول: {e}")
        return web.Response(text=f"❌ حدث خطأ: {e}", status=500)

async def logout_handler(request):
    session_id = request.cookies.get('session_id')
    if session_id:
        delete_session(session_id)
    response = web.Response(status=302, headers={'Location': '/login'})
    response.del_cookie('session_id')
    return response

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

# ===== تسجيل المسارات =====
web_app.router.add_get('/', root_handler)
web_app.router.add_get('/login', login_handler)
web_app.router.add_post('/login', login_handler)
web_app.router.add_get('/logout', logout_handler)
web_app.router.add_get('/health', health_check_handler)

# ===== API Routes =====
web_app.router.add_get('/api/stats', api_stats_handler)
web_app.router.add_get('/api/charts', api_charts_handler)
web_app.router.add_get('/api/export', api_export_handler)
web_app.router.add_get('/api/users', api_users_handler)
web_app.router.add_post('/api/users/{user_id}/toggle-ban', api_user_toggle_ban_handler)
web_app.router.add_get('/api/channels', api_channels_handler)
web_app.router.add_get('/api/groups', api_groups_handler)
web_app.router.add_get('/api/posts', api_posts_handler)
web_app.router.add_get('/api/contests', api_contests_handler)
web_app.router.add_get('/api/logs', api_logs_handler)
web_app.router.add_delete('/api/logs', api_logs_delete_handler)
web_app.router.add_get('/api/backups', api_backups_handler)
web_app.router.add_post('/api/backups', api_backup_create_handler)
web_app.router.add_post('/api/backups/{name}/restore', api_backup_restore_handler)
web_app.router.add_delete('/api/backups/{name}', api_backup_delete_handler)
web_app.router.add_get('/api/settings', api_settings_handler)
web_app.router.add_post('/api/settings', api_settings_update_handler)
web_app.router.add_get('/api/system-info', api_system_info_handler)

# ===== WebSocket Manager =====
class WebSocketManager:
    def __init__(self):
        self.connections = set()
        self.lock = asyncio.Lock()

    async def broadcast(self, data: dict):
        async with self.lock:
            if not self.connections:
                return
            message = json.dumps(data)
            to_remove = []
            for ws in self.connections:
                try:
                    await ws.send_str(message)
                except:
                    to_remove.append(ws)
            for ws in to_remove:
                self.connections.discard(ws)

    async def handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async with self.lock:
            self.connections.add(ws)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        if data.get('type') == 'ping':
                            await ws.send_str(json.dumps({'type': 'pong'}))
                    except:
                        pass
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"خطأ في WebSocket: {ws.exception()}")
        finally:
            async with self.lock:
                self.connections.discard(ws)
        return ws

ws_manager = WebSocketManager()
web_app.router.add_get('/ws', ws_manager.handler)

# ===== WebSocket Extended =====
class WebSocketExtendedHandler:
    def __init__(self):
        self.connections = {}
        self.subscriptions = defaultdict(set)
        self.lock = asyncio.Lock()

    async def handle_auth(self, ws, token: str):
        if token == WEB_SECRET_KEY:
            self.connections[token] = ws
            await ws.send_str(json.dumps({'type': 'auth', 'status': 'success'}))
            return True
        await ws.send_str(json.dumps({'type': 'auth', 'status': 'failed'}))
        return False

    async def handle_subscribe(self, ws, channel: str):
        async with self.lock:
            self.subscriptions[channel].add(ws)
            await ws.send_str(json.dumps({'type': 'subscribe', 'channel': channel, 'status': 'success'}))

    async def handle_unsubscribe(self, ws, channel: str):
        async with self.lock:
            if channel in self.subscriptions:
                self.subscriptions[channel].discard(ws)
            await ws.send_str(json.dumps({'type': 'unsubscribe', 'channel': channel, 'status': 'success'}))

    async def broadcast(self, channel: str, data: dict):
        async with self.lock:
            if channel in self.subscriptions:
                message = json.dumps({'type': 'broadcast', 'channel': channel, 'data': data})
                for ws in list(self.subscriptions[channel]):
                    try:
                        await ws.send_str(message)
                    except:
                        self.subscriptions[channel].discard(ws)

    async def get_stats(self) -> dict:
        total, banned, posts, groups, channels = await db_stats()
        return {
            'total_users': total,
            'banned_users': banned,
            'pending_posts': posts,
            'groups': groups,
            'channels': channels
        }

ws_extended = WebSocketExtendedHandler()

async def websocket_extended_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    token = request.query.get('token')
    if not token:
        await ws.close()
        return ws
    authenticated = await ws_extended.handle_auth(ws, token)
    if not authenticated:
        await ws.close()
        return ws
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    action = data.get('action')
                    if action == 'subscribe':
                        channel = data.get('channel')
                        if channel:
                            await ws_extended.handle_subscribe(ws, channel)
                    elif action == 'unsubscribe':
                        channel = data.get('channel')
                        if channel:
                            await ws_extended.handle_unsubscribe(ws, channel)
                    elif action == 'get_stats':
                        stats = await ws_extended.get_stats()
                        await ws.send_str(json.dumps({'type': 'response', 'action': 'get_stats', 'data': stats}))
                    elif action == 'ping':
                        await ws.send_str(json.dumps({'type': 'pong'}))
                except Exception as e:
                    await ws.send_str(json.dumps({'type': 'error', 'message': str(e)}))
    except Exception as e:
        logger.error(f"خطأ في WebSocket: {e}")
    finally:
        for channel in list(ws_extended.subscriptions):
            ws_extended.subscriptions[channel].discard(ws)
    return ws

web_app.router.add_get('/ws_extended', websocket_extended_handler)
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

# ===================== دوال الأمان والمشرفين =====================
async def db_register_hidden_owner_group(chat_id: int, owner_id: int):
    async def _register(conn):
        await conn.execute("INSERT OR REPLACE INTO hidden_owner_groups (chat_id, owner_id, is_hidden) VALUES (?, ?, 1)", (chat_id, owner_id))
        await conn.execute("INSERT OR IGNORE INTO user_groups_link (user_id, chat_id) VALUES (?, ?)", (owner_id, chat_id))
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
            await conn.execute("INSERT OR IGNORE INTO hidden_admins (chat_id, admin_id, added_by, added_at) VALUES (?, ?, ?, ?)",
                              (chat_id, admin_id, added_by, utc_now_iso()))
            await conn.execute("INSERT OR IGNORE INTO user_groups_link (user_id, chat_id) VALUES (?, ?)", (admin_id, chat_id))
            await conn.commit()
            return True
        except:
            return False
    return await execute_db(_add)

async def db_remove_hidden_admin(chat_id: int, admin_id: int) -> bool:
    async def _remove(conn):
        await conn.execute("DELETE FROM hidden_admins WHERE chat_id=? AND admin_id=?", (chat_id, admin_id))
        await conn.execute("DELETE FROM user_groups_link WHERE user_id=? AND chat_id=?", (admin_id, chat_id))
        await conn.commit()
        return True
    return await execute_db(_remove)

async def db_is_hidden_admin(chat_id: int, user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT 1 FROM hidden_admins WHERE chat_id=? AND admin_id=?", (chat_id, user_id))
        return await cur.fetchone() is not None
    return await execute_db(_check)

async def db_get_hidden_admins(chat_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT admin_id, added_by, added_at FROM hidden_admins WHERE chat_id=? ORDER BY added_at DESC", (chat_id,))
        rows = await cur.fetchall()
        return [{'admin_id': row[0], 'added_by': row[1], 'added_at': row[2]} for row in rows]
    return await execute_db(_get)

async def db_is_real_admin(chat_id: int, user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT 1 FROM group_admins WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        return await cur.fetchone() is not None
    return await execute_db(_check)

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

# ===================== دوال الجدولة =====================
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
# ===================== دوال القوائم والأزرار (الكيبورد) - الجزء المتبقي =====================
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
        # أزرار جديدة
        [InlineKeyboardButton("🎬 حذف الفيديوهات", callback_data=f"{CallbackData.SECURITY_DELETE_VIDEOS_PREFIX}{chat_id}"),
         InlineKeyboardButton("🛠️ حذف رسائل الخدمة", callback_data=f"{CallbackData.SECURITY_DELETE_SERVICE_PREFIX}{chat_id}")],
        [InlineKeyboardButton("📄 حذف الملفات", callback_data=f"{CallbackData.SECURITY_DELETE_DOCUMENTS_PREFIX}{chat_id}"),
         InlineKeyboardButton("🗑️ حذف الملصقات", callback_data=f"{CallbackData.SECURITY_DELETE_STICKERS_PREFIX}{chat_id}")],  # <-- الزر الجديد
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
                end_date = datetime.strptime(text, "%Y-%m-%d %H:%M")
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
            except ValueError:
                await update.message.reply_text(get_text(user_id, 'contest_date_invalid'))
                logger.warning(f"تنسيق تاريخ غير صحيح من المستخدم {user_id}: {text}")
                return True
            except Exception as e:
                error_id = log_error(e, {'user_id': user_id, 'action': 'create_contest', 'date_input': text})
                await update.message.reply_text(f"❌ حدث خطأ أثناء إنشاء المسابقة (الرمز: `{error_id}`).\nيرجى المحاولة مرة أخرى أو إبلاغ المطور.")
                logger.error(f"خطأ في إنشاء المسابقة: {e}")
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
        await update.message.reply_text(f"❌ حدث خطأ غير متوقع أثناء إنشاء المسابقة (الرمز: `{error_id}`).\nيرجى المحاولة مرة أخرى لاحقاً.")
        context.user_data.pop('state', None)
        return True

# ===================== دوال معالجة الأزرار الجديدة (حذف الفيديوهات، رسائل الخدمة، الملفات، والملصقات) =====================
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

# ===== إضافة جديدة: معالج حذف الملصقات =====
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

# ===================== دوال معالجات الكولباك الأساسية =====================
# (سيتم وضع جميع معالجات الكولباك الموجودة في الكود الأصلي هنا)
# نظراً للطول، سيتم تضمينها في الملف النهائي، لكننا سنشير إليها.
# يجب أن تكون جميع معالجات الكولباك موجودة كما في الإرساليات السابقة.

# ===================== تحسين نظام النبض (Heartbeat) =====================
class HeartbeatSystem:
    """نظام نبض محسن لمراقبة صحة البوت"""
    def __init__(self):
        self.last_ping = time_module.time()
        self.last_pong = time_module.time()
        self.status = "starting"
        self.consecutive_failures = 0
        self.max_failures = 5
        self.check_interval = 30  # ثانية
        self._tasks = []
        self._lock = asyncio.Lock()

    async def start(self, bot):
        """بدء نظام النبض"""
        self.bot = bot
        self._tasks.append(asyncio.create_task(self._telegram_heartbeat()))
        self._tasks.append(asyncio.create_task(self._web_heartbeat()))
        self._tasks.append(asyncio.create_task(self._database_heartbeat()))
        self._tasks.append(asyncio.create_task(self._memory_heartbeat()))
        logger.info("❤️ تم تفعيل نظام النبض المحسن")

    async def _telegram_heartbeat(self):
        """التحقق من اتصال تيليجرام"""
        while True:
            try:
                await asyncio.sleep(self.check_interval)
                start = time_module.time()
                me = await self.bot.get_me()
                duration = time_module.time() - start
                self.last_pong = time_module.time()
                self.consecutive_failures = 0
                self.status = "healthy"
                logger.debug(f"❤️ نبض تيليجرام: {me.username} - {duration:.2f}s")
            except Exception as e:
                self.consecutive_failures += 1
                self.status = "unhealthy"
                logger.warning(f"⚠️ فشل نبض تيليجرام ({self.consecutive_failures}/{self.max_failures}): {e}")
                if self.consecutive_failures >= self.max_failures:
                    self.status = "critical"
                    await security_audit.log("HEARTBEAT_FAILURE", 0, {"type": "telegram", "failures": self.consecutive_failures}, "CRITICAL")
                await asyncio.sleep(min(60, self.check_interval * self.consecutive_failures))

    async def _web_heartbeat(self):
        """التحقق من خادم الويب"""
        while True:
            try:
                await asyncio.sleep(self.check_interval * 2)
                port = WEB_PORT_USED or WEB_PORT
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
                        if resp.status == 200:
                            logger.debug(f"❤️ نبض الويب: OK (port {port})")
                        else:
                            logger.warning(f"⚠️ نبض الويب: status {resp.status}")
            except Exception as e:
                logger.warning(f"⚠️ فشل نبض الويب: {e}")
                await asyncio.sleep(60)

    async def _database_heartbeat(self):
        """التحقق من قاعدة البيانات"""
        while True:
            try:
                await asyncio.sleep(self.check_interval * 3)
                async def _check(conn):
                    cur = await conn.execute("SELECT 1")
                    return await cur.fetchone() is not None
                healthy = await execute_db(_check)
                if healthy:
                    logger.debug("❤️ نبض قاعدة البيانات: OK")
                else:
                    logger.warning("⚠️ نبض قاعدة البيانات: فشل")
            except Exception as e:
                logger.warning(f"⚠️ فشل نبض قاعدة البيانات: {e}")
                await asyncio.sleep(60)

    async def _memory_heartbeat(self):
        """مراقبة الذاكرة"""
        while True:
            try:
                await asyncio.sleep(self.check_interval * 4)
                ram = get_ram_usage()
                if ram['percent'] > 85:
                    logger.warning(f"⚠️ استخدام الذاكرة مرتفع: {ram['percent']}%")
                    memory_optimizer()
                elif ram['percent'] > 70:
                    logger.info(f"📊 استخدام الذاكرة: {ram['percent']}%")
            except Exception as e:
                logger.warning(f"⚠️ فشل مراقبة الذاكرة: {e}")

    async def get_status(self) -> dict:
        """الحصول على حالة النظام"""
        uptime = time_module.time() - getattr(heartbeat_system, 'start_time', time_module.time())
        return {
            'status': self.status,
            'uptime': uptime,
            'last_ping': self.last_ping,
            'last_pong': self.last_pong,
            'consecutive_failures': self.consecutive_failures,
            'max_failures': self.max_failures,
            'telegram_connected': self.consecutive_failures == 0,
            'timestamp': mecca_now_iso()
        }

    async def stop(self):
        """إيقاف نظام النبض"""
        for task in self._tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("🛑 تم إيقاف نظام النبض")

heartbeat_system = HeartbeatSystem()
heartbeat_system.start_time = time_module.time()

# ===================== الدالة الرئيسية (main) =====================
async def main():
    await init_db_improved()
    await import_banned_words_on_startup()
    load_all_languages()
    
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

    # ========== CallbackQuery Handlers (الأساسية) ==========
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

    # ========== الأزرار الجديدة (حذف الفيديوهات، رسائل الخدمة، الملفات، والملصقات) ==========
    application.add_handler(CallbackQueryHandler(security_delete_videos_callback, pattern=f"^{CallbackData.SECURITY_DELETE_VIDEOS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_delete_service_callback, pattern=f"^{CallbackData.SECURITY_DELETE_SERVICE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_delete_documents_callback, pattern=f"^{CallbackData.SECURITY_DELETE_DOCUMENTS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_delete_stickers_callback, pattern=f"^{CallbackData.SECURITY_DELETE_STICKERS_PREFIX}"))  # <-- التسجيل الجديد

    # ========== بقية المعالجات ==========
    application.add_handler(CallbackQueryHandler(security_links_callback, pattern=f"^{CallbackData.SECURITY_LINKS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_mentions_callback, pattern=f"^{CallbackData.SECURITY_MENTIONS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_warn_callback, pattern=f"^{CallbackData.SECURITY_WARN_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_slowmode_callback, pattern=f"^{CallbackData.SECURITY_SLOWMODE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_banned_words_menu_callback, pattern=f"^{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_welcome_callback, pattern=f"^{CallbackData.SECURITY_WELCOME_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_goodbye_callback, pattern=f"^{CallbackData.SECURITY_GOODBYE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_close_callback, pattern=f"^{CallbackData.SECURITY_CLOSE}$"))
    application.add_handler(CallbackQueryHandler(security_main_callback, pattern=f"^{CallbackData.SECURITY_MAIN}$"))

    # ========== معالجات الكولباك الإضافية ==========
    application.add_handler(CallbackQueryHandler(contests_menu_callback, pattern=f"^{CallbackData.CONTESTS_MENU}$"))
    application.add_handler(CallbackQueryHandler(contest_join_callback, pattern=f"^{CallbackData.CONTEST_JOIN_PREFIX}"))
    application.add_handler(CallbackQueryHandler(contest_winners_callback, pattern=f"^{CallbackData.CONTEST_WINNERS}$"))
    application.add_handler(CallbackQueryHandler(contests_back_callback, pattern=f"^{CallbackData.CONTESTS_BACK}$"))
    application.add_handler(CallbackQueryHandler(admin_create_contest_callback, pattern=f"^{CallbackData.ADMIN_CREATE_CONTEST}$"))
    application.add_handler(CallbackQueryHandler(admin_declare_winner_callback, pattern=f"^{CallbackData.ADMIN_DECLARE_WINNER}$"))

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

    # ========== أوامر البوت ==========
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

    # ========== بدء المهام الخلفية ==========
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

    # ========== تشغيل نظام النبض المحسن ==========
    await heartbeat_system.start(application.bot)

    print(f"🚀 تم تشغيل {BOT_NAME} (الإصدار 19.3.3)")
    print("✅ جميع التحسينات المطلوبة تم تطبيقها:")
    print("   • ✅ أزرار جديدة: حذف الفيديوهات، رسائل الخدمة، الملفات، والملصقات")
    print("   • ✅ تحديث قاعدة البيانات (group_security)")
    print("   • ✅ تحسين filter_messages_handler")
    print("   • ✅ إضافة معالجات الكولباك الجديدة")
    print("   • ✅ تحديث لوحة الأمان security_keyboard")
    print("   • ✅ نظام نبض محسن (Heartbeat) مع مراقبة تيليجرام، الويب، قاعدة البيانات، والذاكرة")
    print("   • ✅ إعادة محاولة ذكية مع Jitter")
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
        await heartbeat_system.stop()
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
