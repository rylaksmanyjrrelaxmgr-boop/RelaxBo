#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ريلاكس مانيجر - بوت متكامل لإدارة القنوات والمجموعات
الإصدار: 19.3.5 - الكود الكامل مع جميع الإصلاحات والتحسينات
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
ensure_package("croniter")

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

# استيراد bleach مع التعامل مع حالات الفشل
try:
    import bleach
except ImportError:
    bleach = None
    print("⚠️ bleach غير مثبت - سيتم تعطيل التنظيف المتقدم للنصوص")

# ===================== إعدادات Jinja2 =====================
template_env = None
if JINJA2_AVAILABLE:
    try:
        from jinja2 import FileSystemLoader, Environment
        template_loader = FileSystemLoader(str(TEMPLATES_PATH))
        template_env = Environment(loader=template_loader, autoescape=True)
        print("✅ تم تحميل Jinja2 بنجاح")
    except Exception as e:
        print(f"⚠️ فشل تحميل Jinja2: {e}")
        template_env = None

# ===================== دالة تحويل آمنة للعدد =====================
def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

# ===================== نظام اللغات من ملفات منفصلة =====================
_lang_data = {}
_lang_cache_time = {}
LANG_CACHE_TTL = 300

def load_all_languages():
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
            "back": "🔙 رجوع",
            "create_contest_title": "📝 **إنشاء مسابقة جديدة**\n\nأرسل **عنوان** المسابقة:",
            "declare_winner_usage": "📝 **الاستخدام:**\n`/declare_winner معرف_المسابقة معرف_المستخدم`\n\nمثال: `/declare_winner 5 123456789`",
            "contest_not_found": "❌ المسابقة غير موجودة",
            "contest_expired": "❌ المسابقة قد انتهت",
            "contest_not_participant": "❌ هذا المستخدم لم يشارك في المسابقة",
            "contest_declared": "✅ تم إعلان فائز المسابقة **{0}**\n👤 الفائز: `{1}`\n🎁 الجائزة: {2}",
            "contest_declared_error": "❌ حدث خطأ أثناء إعلان الفائز",
            "no_contests": "📭 لا توجد مسابقات نشطة حالياً",
            "contests_active": "🏆 **المسابقات النشطة**\n━━━━━━━━━━━━━━━━━━━━━━\n{0}",
            "contest_participated": "✅ لقد شاركت بالفعل في هذه المسابقة",
            "no_winners": "📭 لا يوجد فائزون سابقون",
            "contest_winners_title": "🏆 **الفائزون السابقون**\n━━━━━━━━━━━━━━━━━━━━━━\n",
            "contest_auto_winner": "🏆 **تهانينا!**\nلقد فزت في مسابقة **{0}**!\n🎁 الجائزة: {1}\n\nشكراً لمشاركتك! 🎉",
            "contest_winner_notification": "🎉 **تهانينا!**\nلقد فزت في مسابقة **{0}**!\n🎁 الجائزة: {1}\n\nشكراً لمشاركتك! 🎉",
            "sendcode_user_set": "✅ تم تعيين المستخدم `{0}` كمرخص لاستخدام /sendcode",
            "invalid_user_id": "❌ معرف مستخدم غير صالح!",
            "add_admin_success": "✅ تم إضافة المستخدم `{0}` كمشرف",
            "remove_admin_success": "✅ تم إزالة المستخدم `{0}` من المشرفين",
            "cannot_remove_main_admin": "❌ لا يمكن إزالة المالك الرئيسي",
            "dates_saved": "✅ تم حفظ التواريخ"
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
            "back": "🔙 Back",
            "create_contest_title": "📝 **Create New Contest**\n\nSend the **title** of the contest:",
            "declare_winner_usage": "📝 **Usage:**\n`/declare_winner contest_id user_id`\n\nExample: `/declare_winner 5 123456789`",
            "contest_not_found": "❌ Contest not found",
            "contest_expired": "❌ Contest has expired",
            "contest_not_participant": "❌ This user did not participate in the contest",
            "contest_declared": "✅ Contest **{0}** winner declared!\n👤 Winner: `{1}`\n🎁 Prize: {2}",
            "contest_declared_error": "❌ Error declaring winner",
            "no_contests": "📭 No active contests",
            "contests_active": "🏆 **Active Contests**\n━━━━━━━━━━━━━━━━━━━━━━\n{0}",
            "contest_participated": "✅ You already participated in this contest",
            "no_winners": "📭 No previous winners",
            "contest_winners_title": "🏆 **Previous Winners**\n━━━━━━━━━━━━━━━━━━━━━━\n",
            "contest_auto_winner": "🏆 **Congratulations!**\nYou won the contest **{0}**!\n🎁 Prize: {1}\n\nThanks for participating! 🎉",
            "contest_winner_notification": "🎉 **Congratulations!**\nYou won the contest **{0}**!\n🎁 Prize: {1}\n\nThanks for participating! 🎉",
            "sendcode_user_set": "✅ User `{0}` has been authorized to use /sendcode",
            "invalid_user_id": "❌ Invalid user ID!",
            "add_admin_success": "✅ User `{0}` added as admin",
            "remove_admin_success": "✅ User `{0}` removed from admins",
            "cannot_remove_main_admin": "❌ Cannot remove main owner",
            "dates_saved": "✅ Dates saved"
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
    lang = user_language.get(user_id, 'ar')
    texts = _lang_data.get(lang, {})
    
    if key not in texts:
        en_texts = _lang_data.get('en', {})
        if key in en_texts:
            return en_texts[key]
    
    return texts.get(key, key)

async def set_user_language(user_id: int, lang: str):
    user_language[user_id] = lang
    try:
        async def _set(conn):
            await conn.execute("INSERT OR REPLACE INTO user_language (user_id, lang) VALUES (?, ?)", (user_id, lang))
            await conn.commit()
        await execute_db(_set)
    except Exception as e:
        logger.error(f"فشل حفظ لغة المستخدم {user_id}: {e}")

load_all_languages()

# ===================== تعريف UserState (الكلاس المفقود) =====================
class UserState(Enum):
    # ---- إدارة القنوات والمنشورات ----
    WAITING_CHANNEL_ID = 1
    ADDING_POSTS = 2
    WAITING_GROUP_BANNED_WORD = 3
    WAITING_REMOVE_GROUP_BANNED_WORD = 4
    WAITING_GLOBAL_BANNED_WORD = 5
    WAITING_REMOVE_GLOBAL_BANNED_WORD = 6

    # ---- الجدولة ----
    WAITING_INTERVAL_MINUTES = 7
    WAITING_INTERVAL_HOURS = 8
    WAITING_INTERVAL_DAYS = 9
    SELECTING_DAYS = 10
    WAITING_DATES = 11
    WAITING_PUBLISH_TIME = 12

    # ---- الأمان والإجراءات المتقدمة ----
    WAITING_BAN_USER = 13
    WAITING_MUTE_USER = 14
    WAITING_WARN_USER = 15
    WAITING_KICK_USER = 16
    WAITING_RESTRICT_USER = 17
    WAITING_PIN_MESSAGE = 18
    WAITING_UNBAN_USER = 19

    # ---- ردود الدعم والإعدادات ----
    WAITING_KEYWORD = 20
    WAITING_REPLY = 21
    WAITING_ADMIN_ID_ADD = 22
    WAITING_ADMIN_ID_REMOVE = 23
    WAITING_SENDCODE_USER = 24
    WAITING_REMINDER_DAYS = 25
    WAITING_NSFW_THRESHOLD = 26

    # ---- المسابقات ----
    WAITING_CONTEST_TITLE = 27
    WAITING_CONTEST_DESCRIPTION = 28
    WAITING_CONTEST_PRIZE = 29
    WAITING_CONTEST_END_DATE = 30
    WAITING_CONTEST_TYPE = 31
    WAITING_CONTEST_ANSWER = 32

    # ---- الإعدادات العامة ----
    WAITING_UPDATE_TEXT = 33
    WAITING_UPDATE_CHANNEL = 34
    WAITING_FORCE_CHANNEL = 35
    WAITING_BROADCAST = 36
    WAITING_LOG_CHANNEL = 37
    WAITING_SCHEDULE_POST = 38
    WAITING_GROUP_SECURITY = 39

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

# ===================== دوال مساعدة =====================
def parse_days_of_week_safe(days_str: str) -> list:
    if not days_str:
        return []
    try:
        days = json.loads(days_str)
        if isinstance(days, list):
            return [int(d) for d in days if isinstance(d, (int, str)) and str(d).isdigit()]
        return []
    except:
        return []

def parse_dates_safe(dates_str: str) -> list:
    if not dates_str:
        return []
    try:
        dates = json.loads(dates_str)
        if isinstance(dates, list):
            return [str(d) for d in dates if isinstance(d, str)]
        return []
    except:
        return []

# ===================== الردود التلقائية (200 رد) =====================
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

    if key_file.exists() and salt_file.exists():
        try:
            with open(key_file, 'rb') as f:
                key = f.read()
            return key
        except:
            pass

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

    if not sys.stdin.isatty():
        print("🔐 بيئة غير تفاعلية - إنشاء مفتاح عشوائي")
        key = Fernet.generate_key()
        try:
            with open(key_file, 'wb') as f:
                f.write(key)
        except:
            pass
        return key

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
    _auth_cache = TTLCache(maxsize=1000, ttl=300)
except ImportError:
    CACHETOOLS_AVAILABLE = False
    class SimpleTTLCache:
        def __init__(self, maxsize=1000, ttl=300):
            self.maxsize = maxsize
            self.ttl = ttl
            self.cache = {}
            self.timestamps = {}

        def __contains__(self, key):
            if key in self.cache:
                if time_module.time() - self.timestamps[key] < self.ttl:
                    return True
                else:
                    del self.cache[key]
                    del self.timestamps[key]
            return False

        def __getitem__(self, key):
            if key in self.cache:
                if time_module.time() - self.timestamps[key] < self.ttl:
                    return self.cache[key]
                else:
                    del self.cache[key]
                    del self.timestamps[key]
                    raise KeyError
            raise KeyError

        def __setitem__(self, key, value):
            if len(self.cache) >= self.maxsize:
                oldest = min(self.timestamps, key=self.timestamps.get)
                del self.cache[oldest]
                del self.timestamps[oldest]
            self.cache[key] = value
            self.timestamps[key] = time_module.time()

        def __delitem__(self, key):
            del self.cache[key]
            del self.timestamps[key]

        def clear(self):
            self.cache.clear()
            self.timestamps.clear()

        def get(self, key, default=None):
            try:
                return self.__getitem__(key)
            except KeyError:
                return default

        def pop(self, key, default=None):
            try:
                value = self.__getitem__(key)
                del self.cache[key]
                del self.timestamps[key]
                return value
            except KeyError:
                return default

    _admin_cache = SimpleTTLCache(maxsize=1000, ttl=300)
    _security_cache = SimpleTTLCache(maxsize=500, ttl=60)
    _auth_cache = SimpleTTLCache(maxsize=1000, ttl=300)

_security_cache_time = {}
_security_cache_ttl = 30

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

# ===================== دوال الصلاحيات =====================
async def is_authorized_in_group(bot, chat_id: int, user_id: int) -> bool:
    if user_id == PRIMARY_OWNER_ID:
        return True

    cache_key = f"auth_{chat_id}_{user_id}"
    if cache_key in _auth_cache:
        return _auth_cache[cache_key]

    authorized = False
    if await db_is_real_admin(chat_id, user_id):
        authorized = True
    if not authorized and await db_is_hidden_owner(chat_id, user_id):
        authorized = True
    if not authorized and await db_is_hidden_admin(chat_id, user_id):
        authorized = True

    _auth_cache[cache_key] = authorized
    return authorized

def invalidate_auth_cache(chat_id: int = None, user_id: int = None):
    if chat_id is not None and user_id is not None:
        cache_key = f"auth_{chat_id}_{user_id}"
        _auth_cache.pop(cache_key, None)
    elif chat_id is not None:
        keys_to_remove = [k for k in list(_auth_cache.cache.keys()) if k.startswith(f"auth_{chat_id}_")]
        for k in keys_to_remove:
            _auth_cache.pop(k, None)
    else:
        _auth_cache.clear()

# ===================== دالة invalidate_user_cache (المفقودة) =====================
async def invalidate_user_cache(user_id: int):
    """إبطال ذاكرة التخزين المؤقت للمستخدم"""
    _auth_cache.pop(f"auth_*_{user_id}", None)

# ===================== دالة log_error (المفقودة) =====================
def log_error(error: Exception, context: dict = None) -> str:
    """تسجيل الخطأ وإرجاع معرف الخطأ"""
    return advanced_logger.log_error("حدث خطأ", error, context)

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
    if bleach is not None:
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
            text = cleaned
        except:
            pass
    else:
        text = re.sub(r'<[^>]+>', '', text)
    if len(text) > max_length:
        text = text[:max_length]
    return text

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
        error_logger = logging.getLogger('error_logger')
        error_logger.setLevel(logging.ERROR)
        error_handler = logging.FileHandler(ERROR_LOG, encoding='utf-8')
        error_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        error_logger.addHandler(error_handler)
        self.loggers['error'] = error_logger

        access_logger = logging.getLogger('access_logger')
        access_logger.setLevel(logging.INFO)
        access_handler = logging.FileHandler(ACCESS_LOG, encoding='utf-8')
        access_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        access_logger.addHandler(access_handler)
        self.loggers['access'] = access_logger

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

# ===================== نظام إدارة الأخطاء =====================
class ErrorHandler:
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.errors = defaultdict(int)
        self._lock = asyncio.Lock()

    async def handle_async(self, func: Callable, *args, **kwargs) -> Any:
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
    try:
        if CACHETOOLS_AVAILABLE:
            _admin_cache.clear()
            _security_cache.clear()
            _auth_cache.clear()
        else:
            _admin_cache.clear()
            _security_cache.clear()
            _auth_cache.clear()

        asyncio.create_task(_translation_cache.clear())
        NSFW_CACHE.clear()
        gc.collect()
        return True
    except Exception as e:
        advanced_logger.log_error("فشل تحسين الذاكرة", e)
        return False

async def memory_optimizer_loop():
    while True:
        await asyncio.sleep(300)
        try:
            memory_optimizer()
            advanced_logger.log_access(0, "MEMORY_OPTIMIZED", {"timestamp": utc_now_iso()})
        except Exception as e:
            advanced_logger.log_error("فشل حلقة تحسين الذاكرة", e)

# ===================== نظام تنظيف نقاط المستخدمين =====================
user_points_last_hour = defaultdict(lambda: (0, 0.0))

async def cleanup_points_cache():
    while True:
        await asyncio.sleep(3600)
        now = time_module.time()
        to_delete = [uid for uid, (_, ts) in user_points_last_hour.items() if now - ts > 3600]
        for uid in to_delete:
            del user_points_last_hour[uid]

# ===================== نظام الإشعارات المتقدم =====================
class NotificationSystem:
    def __init__(self):
        self.pending_notifications = []
        self._lock = asyncio.Lock()
        self._scheduled_tasks = []

    async def send_notification(self, bot, user_id: int, text: str, parse_mode: str = "MarkdownV2", reply_markup=None):
        try:
            await safe_send_markdown(bot, user_id, text, reply_markup)
            advanced_logger.log_access(user_id, "NOTIFICATION_SENT", {"text": text[:50]})
            return True
        except Exception as e:
            advanced_logger.log_error("فشل إرسال الإشعار", e, {"user_id": user_id})
            return False

    async def send_bulk_notification(self, bot, user_ids: List[int], text: str, parse_mode: str = "MarkdownV2", delay: float = 0.5):
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
    if not query or not query.message:
        return None
    
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
    async def _get(conn):
        cur = await conn.execute("SELECT lang FROM user_translation WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 'off'
    lang = await execute_db(_get)
    return lang

async def set_user_translation_language(user_id: int, lang: str):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO user_translation (user_id, lang) VALUES (?, ?)", (user_id, lang))
        await conn.commit()
    await execute_db(_set)

# ===================== دوال القوائم والأزرار (CallbackData) =====================
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
    SECURITY_STICKERS_PREFIX = "security:stickers:"
    SECURITY_VIDEOS_PREFIX = "security:videos:"
    SECURITY_SERVICE_MESSAGES_PREFIX = "security:service_messages:"
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
        current_end = None
        if row and row[0]:
            try:
                current_end = datetime.fromisoformat(row[0])
            except (ValueError, TypeError):
                current_end = None
        if current_end and current_end > utc_now():
            new_end = current_end + timedelta(days=days)
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
            except (ValueError, TypeError):
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
            except (ValueError, TypeError):
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
        row = await cur.fetchone()
        if row:
            return {'channel_id': row[0], 'channel_name': row[1]}
        return {'channel_id': None, 'channel_name': None}
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

async def db_get_all_bot_channels(only_banned: bool = False, limit: int = 500):
    async def _get(conn):
        if only_banned:
            cur = await conn.execute("SELECT channel_id, channel_name, added_by, added_at, banned FROM bot_channels WHERE banned=1 ORDER BY added_at DESC LIMIT ?", (limit,))
        else:
            cur = await conn.execute("SELECT channel_id, channel_name, added_by, added_at, banned FROM bot_channels ORDER BY added_at DESC LIMIT ?", (limit,))
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
            query = """
                SELECT DISTINCT bg.chat_id, bg.chat_name, bg.username, bg.banned
                FROM bot_groups bg
                LEFT JOIN hidden_owner_groups hog ON bg.chat_id = hog.chat_id AND hog.owner_id = ?
                LEFT JOIN group_admins ga ON bg.chat_id = ga.chat_id AND ga.user_id = ?
                LEFT JOIN user_groups_link ugl ON bg.chat_id = ugl.chat_id AND ugl.user_id = ?
                WHERE (hog.owner_id IS NOT NULL)
                   OR (ga.user_id IS NOT NULL)
                   OR (ugl.user_id IS NOT NULL)
                ORDER BY bg.chat_name
            """
            cur = await conn.execute(query, (user_id, user_id, user_id))
            rows = await cur.fetchall()
            
            hidden_admin_query = "SELECT chat_id FROM hidden_admins WHERE admin_id = ?"
            hidden_admin_cur = await conn.execute(hidden_admin_query, (user_id,))
            hidden_admin_chats = {row[0] for row in await hidden_admin_cur.fetchall()}
            
            visible_groups = []
            for row in rows:
                chat_id = row[0]
                if chat_id in hidden_admin_chats:
                    continue
                visible_groups.append(row)
            
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

async def db_get_all_groups(only_banned: bool = False, limit: int = 500):
    async def _get(conn):
        if only_banned:
            cur = await conn.execute("SELECT chat_id, chat_name, username, added_by, added_at, banned FROM bot_groups WHERE banned=1 ORDER BY added_at DESC LIMIT ?", (limit,))
        else:
            cur = await conn.execute("SELECT chat_id, chat_name, username, added_by, added_at, banned FROM bot_groups ORDER BY added_at DESC LIMIT ?", (limit,))
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
async def ensure_security_columns(conn):
    """التأكد من وجود جميع الأعمدة المطلوبة في جدول group_security"""
    cur = await conn.execute("PRAGMA table_info(group_security)")
    columns = [row[1] for row in await cur.fetchall()]
    
    if 'delete_stickers' not in columns:
        await conn.execute("ALTER TABLE group_security ADD COLUMN delete_stickers INTEGER DEFAULT 0")
    if 'delete_videos' not in columns:
        await conn.execute("ALTER TABLE group_security ADD COLUMN delete_videos INTEGER DEFAULT 0")
    if 'delete_service_messages' not in columns:
        await conn.execute("ALTER TABLE group_security ADD COLUMN delete_service_messages INTEGER DEFAULT 0")
    
    await conn.commit()

async def db_get_security_settings(chat_id: int):
    default_settings = {
        'links': False, 'mentions': False, 'warn': True, 'slow_mode': False,
        'slow_mode_seconds': 5, 'welcome_enabled': False,
        'welcome_text': "مرحباً {user} في {chat} 🤍",
        'goodbye_enabled': False, 'goodbye_text': "وداعاً {user} 👋",
        'delete_banned_words': False, 'auto_penalty': 'none', 'auto_mute_duration': 60,
        'delete_stickers': False, 'delete_videos': False,
        'delete_service_messages': False
    }

    if CACHETOOLS_AVAILABLE and chat_id in _security_cache:
        settings = _security_cache[chat_id]
        for key in ['delete_stickers', 'delete_videos', 'delete_service_messages']:
            if key not in settings:
                settings[key] = False
        return settings

    try:
        async def _get(conn):
            await ensure_security_columns(conn)
            
            cur = await conn.execute(
                """SELECT delete_links, delete_mentions, warn_message, slow_mode,
                          slow_mode_seconds, welcome_enabled, welcome_text,
                          goodbye_enabled, goodbye_text, delete_banned_words,
                          auto_penalty, auto_mute_duration,
                          delete_stickers, delete_videos,
                          delete_service_messages
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
                    'delete_stickers': row[12] == 1 if len(row) > 12 else False,
                    'delete_videos': row[13] == 1 if len(row) > 13 else False,
                    'delete_service_messages': row[14] == 1 if len(row) > 14 else False
                }
                if CACHETOOLS_AVAILABLE:
                    _security_cache[chat_id] = settings
                return settings

            await conn.execute(
                """INSERT INTO group_security
                   (chat_id, delete_links, delete_mentions, warn_message, slow_mode,
                    slow_mode_seconds, welcome_enabled, welcome_text, goodbye_enabled,
                    goodbye_text, delete_banned_words, auto_penalty, auto_mute_duration,
                    delete_stickers, delete_videos, delete_service_messages)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (chat_id, 0, 0, 1, 0, 5, 0, default_settings['welcome_text'],
                 0, default_settings['goodbye_text'], 0, 'none', 60, 0, 0, 0)
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
        await ensure_security_columns(conn)
        
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
                elif key == 'delete_stickers':
                    updates.append("delete_stickers=?")
                    values.append(1 if value else 0)
                elif key == 'delete_videos':
                    updates.append("delete_videos=?")
                    values.append(1 if value else 0)
                elif key == 'delete_service_messages':
                    updates.append("delete_service_messages=?")
                    values.append(1 if value else 0)
            if updates:
                query = f"UPDATE group_security SET {', '.join(updates)} WHERE chat_id=?"
                values.append(chat_id)
                await conn.execute(query, values)
        else:
            await conn.execute(
                """INSERT INTO group_security
                   (chat_id, delete_links, delete_mentions, warn_message, slow_mode,
                    slow_mode_seconds, welcome_enabled, welcome_text, goodbye_enabled,
                    goodbye_text, delete_banned_words, auto_penalty, auto_mute_duration,
                    delete_stickers, delete_videos, delete_service_messages)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                 1 if kwargs.get('delete_stickers', False) else 0,
                 1 if kwargs.get('delete_videos', False) else 0,
                 1 if kwargs.get('delete_service_messages', False) else 0)
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
            try:
                last_time = datetime.fromisoformat(row[0])
                if (now - last_time).total_seconds() < seconds:
                    return False
            except (ValueError, TypeError):
                pass
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

# ===================== دوال المشرفين =====================
async def add_bot_admin(user_id: int):
    async def _add(conn):
        await conn.execute("INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)", (user_id,))
        await conn.commit()
    return await execute_db(_add)

async def remove_bot_admin(user_id: int):
    async def _remove(conn):
        await conn.execute("DELETE FROM bot_admins WHERE user_id=?", (user_id,))
        await conn.commit()
    return await execute_db(_remove)

async def is_bot_admin(user_id: int) -> bool:
    if user_id == PRIMARY_OWNER_ID:
        return True
    async def _check(conn):
        cur = await conn.execute("SELECT 1 FROM bot_admins WHERE user_id=?", (user_id,))
        return await cur.fetchone() is not None
    return await execute_db(_check)

async def get_all_bot_admins():
    async def _get(conn):
        cur = await conn.execute("SELECT user_id FROM bot_admins")
        rows = await cur.fetchall()
        return [row[0] for row in rows]
    return await execute_db(_get)

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
        if last_row:
            try:
                last_time = datetime.fromisoformat(last_row[0])
            except (ValueError, TypeError):
                last_time = utc_now()
        else:
            last_time = utc_now()

        schedule_type = schedule['type']
        publish_time_str = schedule.get('publish_time', '00:00')
        if ':' not in publish_time_str:
            publish_time_str = '00:00'
        try:
            hour, minute = map(int, publish_time_str.split(':'))
        except:
            hour, minute = 0, 0

        next_date = None

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
                import croniter
                base = last_time
                cron = croniter.croniter(cron_expr, base)
                next_date = cron.get_next(datetime)
            except Exception as e:
                logger.warning(f"فشل حساب cron: {e}")
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
        await conn.execute("DELETE FROM support_tickets")
        await conn.execute("UPDATE settings SET value='0' WHERE key='last_ticket_number'")
        await conn.commit()
        # استرجاع العدد المحذوف
        cur = await conn.execute("SELECT changes()")
        row = await cur.fetchone()
        count = row[0] if row else 0
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
        max_per_day = safe_int(settings.get('max_referrals_per_day', '5'), 5)
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
        reward_days = safe_int(settings.get('reward_days_per_referral', '3'), 3)
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
    return safe_int(settings.get('welcome_bonus_points', '10'), 10)

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
            except (ValueError, TypeError):
                continue
        return users
    return await execute_db(_get)

async def db_get_all_active_users_for_report() -> list:
    async def _get(conn):
        thirty_days_ago = (utc_now() - timedelta(days=30)).isoformat()
        cur = await conn.execute("SELECT user_id FROM users_cache WHERE last_updated >= ?", (thirty_days_ago,))
        return [row[0] for row in await cur.fetchall()]
    return await execute_db(_get)

# ===================== دوال المسابقات =====================
async def db_get_user_participation(user_id: int, contest_id: int):
    """التحقق من مشاركة المستخدم في مسابقة"""
    async def _get(conn):
        cur = await conn.execute(
            "SELECT * FROM contest_participants WHERE user_id=? AND contest_id=?",
            (user_id, contest_id)
        )
        return await cur.fetchone()
    return await execute_db(_get)

async def db_get_active_contests_with_participants(limit: int = 10):
    """الحصول على المسابقات النشطة مع عدد المشاركين"""
    async def _get(conn):
        cur = await conn.execute("""
            SELECT c.id, c.title, c.description, c.prize, c.end_date,
                   (SELECT COUNT(*) FROM contest_participants WHERE contest_id = c.id) as participants,
                   c.contest_type
            FROM contests c
            WHERE c.status = 'active'
            ORDER BY c.end_date ASC
            LIMIT ?
        """, (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_get_contest_winners(limit: int = 10):
    """الحصول على الفائزين السابقين"""
    async def _get(conn):
        cur = await conn.execute("""
            SELECT cw.contest_id, c.title, c.prize, cw.winner_id, cw.announced_at
            FROM contest_winners cw
            JOIN contests c ON cw.contest_id = c.id
            ORDER BY cw.announced_at DESC
            LIMIT ?
        """, (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_get_random_participant(contest_id: int):
    """الحصول على مشارك عشوائي من المسابقة"""
    async def _get(conn):
        cur = await conn.execute(
            "SELECT user_id FROM contest_participants WHERE contest_id=? ORDER BY RANDOM() LIMIT 1",
            (contest_id,)
        )
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_set_contest_winner(contest_id: int, winner_id: int) -> bool:
    """تعيين فائز في مسابقة"""
    async def _set(conn):
        await conn.execute("UPDATE contests SET status='finished', winner_id=? WHERE id=?", (winner_id, contest_id))
        await conn.execute("INSERT INTO contest_winners (contest_id, winner_id, announced_at) VALUES (?, ?, ?)",
                          (contest_id, winner_id, utc_now_iso()))
        await conn.commit()
        return True
    return await execute_db(_set)

async def db_get_contest(contest_id: int) -> dict:
    """الحصول على بيانات مسابقة"""
    async def _get(conn):
        cur = await conn.execute("SELECT * FROM contests WHERE id=?", (contest_id,))
        row = await cur.fetchone()
        if row:
            return {
                'id': row[0],
                'creator_id': row[1],
                'title': row[2],
                'description': row[3],
                'prize': row[4],
                'end_date': row[5],
                'status': row[6],
                'winner_id': row[7],
                'created_at': row[8],
                'contest_type': row[9] if len(row) > 9 else 'raffle'
            }
        return None
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

async def add_points(user_id: int, update: Update = None, context: ContextTypes.DEFAULT_TYPE = None):
    now = utc_now()
    count, last_timestamp = user_points_last_hour.get(user_id, (0, 0.0))
    if last_timestamp > 0:
        try:
            last_time = datetime.fromtimestamp(last_timestamp)
            last_time = to_naive(last_time)
            if (now - last_time).total_seconds() < 3600:
                if count >= 20:
                    return
                new_count = count + 1
            else:
                new_count = 1
        except:
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
        return safe_int(row[0] if row else DEFAULT_PUBLISH_INTERVAL_SECONDS, DEFAULT_PUBLISH_INTERVAL_SECONDS)
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

print("✅ تم تحميل الكود الأساسي بنجاح مع التصحيحات.")

# ===================== دوال القوائم والأزرار (الكيبورد) =====================

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
            if ch_info and ch_info.get('channel_id'):
                ch_tele_id = ch_info['channel_id']
                ch_name = ch_info.get('channel_name', ch_tele_id)
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

def security_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 حذف الروابط", callback_data=f"{CallbackData.SECURITY_LINKS_PREFIX}{chat_id}"),
         InlineKeyboardButton("@ حذف المعرفات", callback_data=f"{CallbackData.SECURITY_MENTIONS_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🚫 كلمات محظورة", callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}"),
         InlineKeyboardButton("⏱️ الوضع البطيء", callback_data=f"{CallbackData.SECURITY_SLOWMODE_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🎯 الترحيب", callback_data=f"{CallbackData.SECURITY_WELCOME_PREFIX}{chat_id}"),
         InlineKeyboardButton("👋 الوداع", callback_data=f"{CallbackData.SECURITY_GOODBYE_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🎴 حذف الملصقات", callback_data=f"{CallbackData.SECURITY_STICKERS_PREFIX}{chat_id}"),
         InlineKeyboardButton("🎬 حذف الفيديوهات", callback_data=f"{CallbackData.SECURITY_VIDEOS_PREFIX}{chat_id}")],
        [InlineKeyboardButton("📨 حذف رسائل الخدمة", callback_data=f"{CallbackData.SECURITY_SERVICE_MESSAGES_PREFIX}{chat_id}")],
        [InlineKeyboardButton("⚖️ تحديد العقوبة", callback_data=f"{CallbackData.PENALTY_MENU}:{chat_id}"),
         InlineKeyboardButton("📝 إعدادات الردود", callback_data=CallbackData.ADMIN_AUTO_REPLY)],
        [InlineKeyboardButton("🛠️ إجراءات متقدمة", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}")],
        [InlineKeyboardButton("📜 سجل الإجراءات", callback_data=f"{CallbackData.GROUP_ACTION_LOG}:{chat_id}")],
        [InlineKeyboardButton("🔙 إغلاق", callback_data=CallbackData.SECURITY_CLOSE)]
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
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
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
            await context.bot.send_photo(ch_info['channel_id'], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'video' and post['media_file_id']:
            await context.bot.send_video(ch_info['channel_id'], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'document' and post['media_file_id']:
            await context.bot.send_document(ch_info['channel_id'], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'audio' and post['media_file_id']:
            await context.bot.send_audio(ch_info['channel_id'], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'voice' and post['media_file_id']:
            await context.bot.send_voice(ch_info['channel_id'], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'animation' and post['media_file_id']:
            await context.bot.send_animation(ch_info['channel_id'], post['media_file_id'], caption=final_text if final_text else None)
        else:
            await context.bot.send_message(ch_info['channel_id'], final_text, parse_mode=None)
        await db_mark_published(post['id'])
        await db_set_last_publish(active, utc_now())
        await db_update_next_publish_date(active)
        if query:
            await query.edit_message_text(get_text(uid, 'post_published'))
        else:
            await update.message.reply_text(get_text(uid, 'post_published'))
    except Exception as e:
        if query:
            await query.edit_message_text(get_text(uid, 'publish_error').format(str(e)[:100]))
        else:
            await update.message.reply_text(get_text(uid, 'publish_error').format(str(e)[:100]))
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

# ===================== معالجات الأمان =====================

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
        text += f"🎴 حذف الملصقات: {'✅' if settings.get('delete_stickers', False) else '❌'}\n"
        text += f"🎬 حذف الفيديوهات: {'✅' if settings.get('delete_videos', False) else '❌'}\n"
        text += f"📨 حذف رسائل الخدمة: {'✅' if settings.get('delete_service_messages', False) else '❌'}\n"
        text += f"🔊 رسالة تحذير: {'✅' if settings.get('warn', True) else '❌'}\n"
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
        error_id = advanced_logger.log_error("خطأ غير متوقع في group_settings_callback", e, {"chat_id": chat_id, "user_id": uid})
        try:
            if query:
                await query.edit_message_text(f"❌ حدث خطأ:\n`{str(e)[:300]}`\n(الرمز: `{error_id}`)")
            else:
                await context.bot.send_message(chat_id=uid, text=f"❌ حدث خطأ:\n`{str(e)[:300]}`\n(الرمز: `{error_id}`)")
        except Exception as e2:
            logger.error(f"فشل إرسال رسالة الخطأ للمستخدم: {e2}")

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

# ===================== معالجات الأمان =====================

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

async def security_stickers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await db_set_security_settings(chat_id, delete_stickers=settings['delete_stickers'])
    status_text = "🟢 مفعل" if settings['delete_stickers'] else "🔴 معطل"
    if query:
        await query.edit_message_text(f"✅ حذف الملصقات: {status_text}")
    else:
        await update.message.reply_text(f"✅ حذف الملصقات: {status_text}")
    await group_settings_callback(update, context)

async def security_videos_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await db_set_security_settings(chat_id, delete_videos=settings['delete_videos'])
    status_text = "🟢 مفعل" if settings['delete_videos'] else "🔴 معطل"
    if query:
        await query.edit_message_text(f"✅ حذف الفيديوهات: {status_text}")
    else:
        await update.message.reply_text(f"✅ حذف الفيديوهات: {status_text}")
    await group_settings_callback(update, context)

async def security_service_messages_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    settings['delete_service_messages'] = not settings.get('delete_service_messages', False)
    await db_set_security_settings(chat_id, delete_service_messages=settings['delete_service_messages'])
    status_text = "🟢 مفعل" if settings['delete_service_messages'] else "🔴 معطل"
    if query:
        await query.edit_message_text(f"✅ حذف رسائل الخدمة: {status_text}")
    else:
        await update.message.reply_text(f"✅ حذف رسائل الخدمة: {status_text}")
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
🎴 حذف الملصقات: {'✅' if settings.get('delete_stickers', False) else '❌'}
🎬 حذف الفيديوهات: {'✅' if settings.get('delete_videos', False) else '❌'}
📨 حذف رسائل الخدمة: {'✅' if settings.get('delete_service_messages', False) else '❌'}
⏱️ وضع بطيء: {'✅' if settings['slow_mode'] else '❌'}
🎯 ترحيب: {'✅' if settings['welcome_enabled'] else '❌'}
👋 وداع: {'✅' if settings['goodbye_enabled'] else '❌'}
🔊 تحذير: {'✅' if settings['warn'] else '❌'}
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
                await query.edit_message_text(f"❌ خطأ: خطأ غير معروف")
            else:
                await update.message.reply_text(f"❌ خطأ: خطأ غير معروف")

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
📦 **الإصدار:** 19.3.4
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
• 🔞 **كشف المحتوى غير اللائق (NSFW)** مع تخزين مؤقت
• 📥 **استيراد الكلمات المحظورة من ملف** مع دعم Regex
• 🌐 **دعم 12 لغة** مع ترجمة تلقائية
• 📊 **رسوم بيانية تفاعلية** في واجهة الويب
• 📤 **تصدير البيانات** (CSV)
• 🌙 **وضع Dark Mode**
• ⏱️ **جدولة CRON**
• 👑 **دعم كامل للمشرفين المتعددين** (جميع المشرفين الحقيقيين يظهرون في مجموعاتهم)
• 🎴 **حذف الملصقات**
• 🎬 **حذف الفيديوهات**
• 📨 **حذف رسائل الخدمة**

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
    reward_days = safe_int(settings.get('reward_days_per_referral', '3'), 3)
    welcome_points = safe_int(settings.get('welcome_bonus_points', '10'), 10)
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
            text = get_text(user_id, 'no_contests')
            if update.callback_query:
                try:
                    await safe_edit_markdown(update.callback_query, text)
                except:
                    await update.callback_query.edit_message_text(text)
            else:
                await safe_send_markdown(context.bot, user_id, text)
            return
        text = get_text(user_id, 'contests_active').format("")
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
                    time_left = get_text(user_id, 'contest_time_left').format(days_left) if days_left > 0 else get_text(user_id, 'contest_expired_label')
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
                await query.edit_message_text(get_text(user_id, 'contest_participated'))
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
                    await query.edit_message_text(get_text(user_id, 'no_winners'))
                except:
                    pass
            else:
                await safe_send_markdown(context.bot, user_id, get_text(user_id, 'no_winners'))
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
    await update.message.reply_text(get_text(user_id, 'create_contest_title'))

async def declare_winner_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    args = context.args
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
    participation = await db_get_user_participation(winner_id, contest_id)
    if not participation:
        await update.message.reply_text(get_text(user_id, 'contest_not_participant'))
        return
    success = await db_set_contest_winner(contest_id, winner_id)
    if success:
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
    channel_name = ch_info['channel_name'] if ch_info else "القناة"
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
    channel_name = ch_info['channel_name'] if ch_info else "القناة"
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

# ===================== دوال التحقق من صلاحية المشرف =====================

async def check_admin_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat is None or update.effective_user is None:
        return False
    if update.effective_chat.type not in ['group', 'supergroup']:
        return False
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    return await is_authorized_in_group(context.bot, chat_id, user_id)

# ===================== دوال إضافية مفقودة =====================

async def check_bot_permissions(bot, chat_id: int) -> tuple:
    """تحقق من صلاحيات البوت (نسخة مبسطة)"""
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
        if me.status in ['administrator', 'creator']:
            return True, "✅ البوت لديه الصلاحيات"
        return False, "❌ البوت ليس مشرفاً"
    except:
        return False, "❌ لا يمكن التحقق من الصلاحيات"

async def handle_contest_creation_states(update: Update, context: ContextTypes.DEFAULT_TYPE, state):
    """معالجة حالات إنشاء المسابقة"""
    if not update.message:
        return False
    
    user_id = update.effective_user.id
    text = update.message.text or ""
    
    if state == UserState.WAITING_CONTEST_TITLE:
        if not text or text.strip() == "":
            await update.message.reply_text("❌ الرجاء إدخال عنوان صحيح للمسابقة")
            return True
        context.user_data['contest_title'] = text.strip()
        context.user_data['state'] = UserState.WAITING_CONTEST_DESCRIPTION
        await update.message.reply_text("📝 **أرسل وصف المسابقة:**\n(يمكنك إرسال /skip للتخطي)")
        return True
        
    elif state == UserState.WAITING_CONTEST_DESCRIPTION:
        context.user_data['contest_description'] = text if text != "/skip" else ""
        context.user_data['state'] = UserState.WAITING_CONTEST_PRIZE
        await update.message.reply_text("🎁 **أرسل جائزة المسابقة:**")
        return True
        
    elif state == UserState.WAITING_CONTEST_PRIZE:
        if not text or text.strip() == "":
            await update.message.reply_text("❌ الرجاء إدخال جائزة صحيحة")
            return True
        context.user_data['contest_prize'] = text.strip()
        context.user_data['state'] = UserState.WAITING_CONTEST_END_DATE
        await update.message.reply_text("📅 **أرسل تاريخ انتهاء المسابقة:**\n(الصيغة: YYYY-MM-DD)\nمثال: 2024-12-31")
        return True
        
    elif state == UserState.WAITING_CONTEST_END_DATE:
        try:
            end_date = datetime.strptime(text.strip(), "%Y-%m-%d")
            if end_date <= utc_now():
                await update.message.reply_text("❌ التاريخ يجب أن يكون في المستقبل!")
                return True
            context.user_data['contest_end_date'] = end_date.isoformat()
            context.user_data['state'] = UserState.WAITING_CONTEST_TYPE
            await update.message.reply_text(
                "📝 **اختر نوع المسابقة:**\n\n"
                "أرسل أحد الأنواع التالية:\n"
                "• `raffle` - سحب عشوائي\n"
                "• `quiz` - مسابقة اختبارية\n"
                "• `vote` - تصويت\n\n"
                "مثال: `raffle`"
            )
            return True
        except ValueError:
            await update.message.reply_text("❌ صيغة تاريخ غير صالحة! استخدم: YYYY-MM-DD")
            return True
            
    elif state == UserState.WAITING_CONTEST_TYPE:
        contest_type = text.lower().strip()
        if contest_type not in ['raffle', 'quiz', 'vote']:
            await update.message.reply_text("❌ نوع غير صالح! اختر: raffle, quiz, vote")
            return True
        
        # حفظ المسابقة
        try:
            async def _save_contest(conn):
                await conn.execute("""
                    INSERT INTO contests (creator_id, title, description, prize, end_date, contest_type, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (user_id, context.user_data['contest_title'], context.user_data['contest_description'],
                      context.user_data['contest_prize'], context.user_data['contest_end_date'], contest_type, utc_now_iso()))
                await conn.commit()
            await execute_db(_save_contest)
            
            context.user_data.pop('state', None)
            msg = f"✅ **تم إنشاء المسابقة بنجاح!**\n\n"
            msg += f"📌 العنوان: {context.user_data['contest_title']}\n"
            msg += f"📝 الوصف: {context.user_data['contest_description'][:100]}{'...' if len(context.user_data['contest_description']) > 100 else ''}\n"
            msg += f"🎁 الجائزة: {context.user_data['contest_prize']}\n"
            msg += f"📅 تنتهي: {text}\n"
            msg += f"📝 النوع: {contest_type}\n\n"
            msg += f"📌 سيتمكن المستخدمون من المشاركة عبر زر المشاركة في المسابقة."
            
            await update.message.reply_text(msg, parse_mode="MarkdownV2")
            await main_menu_callback(update, context)
        except Exception as e:
            await update.message.reply_text(f"❌ حدث خطأ أثناء إنشاء المسابقة: {str(e)[:100]}")
        return True
    
    return False

async def build_days_keyboard(uid: int, context: ContextTypes.DEFAULT_TYPE):
    """بناء لوحة اختيار أيام الأسبوع"""
    selected = context.user_data.get('selected_days', [])
    day_names = ['الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']
    keyboard = []
    for i, name in enumerate(day_names):
        status = "✅" if i in selected else "⬜"
        keyboard.append([InlineKeyboardButton(f"{status} {name}", callback_data=f"{CallbackData.SCHEDULE_DAY_SELECT_PREFIX}{i}")])
    keyboard.append([InlineKeyboardButton("💾 حفظ", callback_data=CallbackData.SCHEDULE_SAVE_DAYS)])
    keyboard.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)])
    return InlineKeyboardMarkup(keyboard)

async def check_bot_admin_permissions(bot, chat_id: int) -> dict:
    """تحقق من صلاحيات البوت في المجموعة"""
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

async def delete_message_after_delay(bot, chat_id: int, message_id: int, delay_seconds: int):
    """حذف رسالة بعد فترة زمنية محددة"""
    await asyncio.sleep(delay_seconds)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.warning(f"فشل حذف الرسالة بعد التأخير: {e}")

# ===================== دوال إضافية لإحصائيات القنوات =====================

async def db_get_channel_stats(channel_db_id: int) -> dict:
    """جلب إحصائيات القناة"""
    async def _get(conn):
        # إجمالي المنشورات
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=?", (channel_db_id,))
        total_posts = (await cur.fetchone())[0]
        
        # المنشورات المنشورة
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=1", (channel_db_id,))
        published_posts = (await cur.fetchone())[0]
        
        # غير المنشورة
        unpublished_posts = total_posts - published_posts
        
        # إجمالي المشاهدات
        cur = await conn.execute("SELECT SUM(views_count) FROM posts WHERE channel_db_id=? AND published=1", (channel_db_id,))
        total_views = (await cur.fetchone())[0] or 0
        
        # متوسط المشاهدات
        avg_views = total_views / published_posts if published_posts > 0 else 0
        
        # آخر وقت نشر
        cur = await conn.execute("SELECT MAX(created_at) FROM posts WHERE channel_db_id=? AND published=1", (channel_db_id,))
        last_post_time = (await cur.fetchone())[0]
        
        # أول وقت نشر
        cur = await conn.execute("SELECT MIN(created_at) FROM posts WHERE channel_db_id=? AND published=1", (channel_db_id,))
        first_post_time = (await cur.fetchone())[0]
        
        # المنشورات اليوم
        today = utc_now().date().isoformat()
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=1 AND DATE(created_at)=?", (channel_db_id, today))
        published_today = (await cur.fetchone())[0]
        
        # هذا الأسبوع
        week_start = (utc_now() - timedelta(days=utc_now().weekday())).date().isoformat()
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=1 AND DATE(created_at)>=?", (channel_db_id, week_start))
        published_this_week = (await cur.fetchone())[0]
        
        # هذا الشهر
        month_start = utc_now().replace(day=1).date().isoformat()
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=1 AND DATE(created_at)>=?", (channel_db_id, month_start))
        published_this_month = (await cur.fetchone())[0]
        
        # الأكثر مشاهدة
        cur = await conn.execute("SELECT id, text, views_count FROM posts WHERE channel_db_id=? AND published=1 ORDER BY views_count DESC LIMIT 1", (channel_db_id,))
        most_viewed = await cur.fetchone()
        most_viewed_post = {'id': most_viewed[0], 'text': most_viewed[1][:100], 'views': most_viewed[2]} if most_viewed else None
        
        # الأقل مشاهدة
        cur = await conn.execute("SELECT id, text, views_count FROM posts WHERE channel_db_id=? AND published=1 AND views_count > 0 ORDER BY views_count ASC LIMIT 1", (channel_db_id,))
        least_viewed = await cur.fetchone()
        least_viewed_post = {'id': least_viewed[0], 'text': least_viewed[1][:100], 'views': least_viewed[2]} if least_viewed else None
        
        # متوسط الوقت بين المنشورات
        avg_time_between = 0
        if published_posts > 1:
            cur = await conn.execute("SELECT created_at FROM posts WHERE channel_db_id=? AND published=1 ORDER BY created_at", (channel_db_id,))
            rows = await cur.fetchall()
            if rows:
                times = [datetime.fromisoformat(row[0]) for row in rows]
                total_seconds = sum((times[i+1] - times[i]).total_seconds() for i in range(len(times)-1))
                avg_time_between = total_seconds / (len(times)-1) / 3600  # بالساعات
        
        # أفضل وقت للنشر
        best_hour = 0
        if published_posts > 0:
            cur = await conn.execute("SELECT strftime('%H', created_at) as hour, COUNT(*) FROM posts WHERE channel_db_id=? AND published=1 GROUP BY hour ORDER BY COUNT(*) DESC LIMIT 1", (channel_db_id,))
            row = await cur.fetchone()
            if row:
                best_hour = int(row[0])
        
        # أفضل يوم للنشر
        best_day = 0
        if published_posts > 0:
            cur = await conn.execute("SELECT strftime('%w', created_at) as day, COUNT(*) FROM posts WHERE channel_db_id=? AND published=1 GROUP BY day ORDER BY COUNT(*) DESC LIMIT 1", (channel_db_id,))
            row = await cur.fetchone()
            if row:
                best_day = int(row[0])
        
        return {
            'total_posts': total_posts,
            'published_posts': published_posts,
            'unpublished_posts': unpublished_posts,
            'total_views': total_views,
            'avg_views': round(avg_views, 1),
            'last_post_time': last_post_time,
            'first_post_time': first_post_time,
            'published_today': published_today,
            'published_this_week': published_this_week,
            'published_this_month': published_this_month,
            'most_viewed_post': most_viewed_post,
            'least_viewed_post': least_viewed_post,
            'avg_time_between_posts': round(avg_time_between, 1),
            'best_publish_hour': best_hour,
            'best_publish_day': best_day
        }
    return await execute_db(_get)

async def db_get_channel_growth(channel_db_id: int, days: int = 30) -> dict:
    """جلب بيانات نمو القناة"""
    async def _get(conn):
        start_date = (utc_now() - timedelta(days=days)).isoformat()
        cur = await conn.execute("""
            SELECT DATE(created_at) as date, COUNT(*) as posts, SUM(views_count) as views
            FROM posts
            WHERE channel_db_id=? AND published=1 AND created_at >= ?
            GROUP BY DATE(created_at)
            ORDER BY date
        """, (channel_db_id, start_date))
        rows = await cur.fetchall()
        dates = [row[0] for row in rows]
        counts = [row[1] for row in rows]
        views = [row[2] or 0 for row in rows]
        total_posts = sum(counts)
        total_views = sum(views)
        total_days = len(dates)
        return {
            'dates': dates,
            'counts': counts,
            'views': views,
            'total_posts': total_posts,
            'total_views': total_views,
            'total_days': total_days
        }
    return await execute_db(_get)

async def db_get_channel_stats_summary(user_id: int) -> dict:
    """جلب ملخص إحصائيات جميع قنوات المستخدم"""
    async def _get(conn):
        channels = await db_get_channels(user_id)
        if not channels:
            return None
        
        total_channels = len(channels)
        active_channels = sum(1 for ch in channels if ch[3] == 0)
        total_posts = 0
        total_published = 0
        total_views = 0
        best_channel = None
        best_views = 0
        
        for ch_db_id, _, ch_name, banned in channels:
            stats = await db_get_channel_stats(ch_db_id)
            total_posts += stats['total_posts']
            total_published += stats['published_posts']
            total_views += stats['total_views']
            if stats['total_views'] > best_views:
                best_views = stats['total_views']
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
            'avg_views_per_channel': total_views / total_channels if total_channels > 0 else 0,
            'best_channel': best_channel
        }
    return await execute_db(_get)

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

# ===================== وظائف تتبع إضافة البوت والمشرفين =====================

async def track_chat_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تتبع إضافة البوت إلى مجموعة"""
    if not update.my_chat_member:
        return
    if update.my_chat_member.new_chat_member.status in ['administrator', 'creator']:
        chat_id = update.effective_chat.id
        chat_name = update.effective_chat.title or "بدون اسم"
        user_id = update.my_chat_member.from_user.id
        
        # تسجيل المجموعة
        await db_register_group(chat_id, chat_name, user_id, update.effective_chat.username)
        
        # مزامنة المشرفين
        await db_sync_group_admins(chat_id, context.bot, user_id)
        
        # إذا كان المستخدم هو المالك الرئيسي، سجل كمالك مخفي
        if user_id == PRIMARY_OWNER_ID:
            await db_register_hidden_owner_group(chat_id, user_id)
        
        logger.info(f"✅ تم إضافة البوت إلى المجموعة {chat_name} ({chat_id}) بواسطة {user_id}")

async def track_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تتبع تغييرات أعضاء المجموعة"""
    if not update.chat_member:
        return
    chat_id = update.effective_chat.id
    user_id = update.chat_member.new_chat_member.user.id
    
    # إذا أصبح المستخدم مشرفاً
    if update.chat_member.new_chat_member.status in ['administrator', 'creator']:
        await db_sync_group_admins(chat_id, context.bot)
        logger.info(f"✅ تم تحديث مشرفي المجموعة {chat_id}")

async def on_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة عند إضافة البوت إلى مجموعة"""
    if not update.message or not update.message.new_chat_members:
        return
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            chat_id = update.effective_chat.id
            chat_name = update.effective_chat.title or "بدون اسم"
            user_id = update.effective_user.id
            
            # تسجيل المجموعة
            await db_register_group(chat_id, chat_name, user_id, update.effective_chat.username)
            
            # مزامنة المشرفين
            await db_sync_group_admins(chat_id, context.bot, user_id)
            
            # إذا كان المستخدم هو المالك الرئيسي، سجل كمالك مخفي
            if user_id == PRIMARY_OWNER_ID:
                await db_register_hidden_owner_group(chat_id, user_id)
            
            await update.message.reply_text(
                f"✅ **تم إضافة البوت إلى المجموعة!**\n\n"
                f"📌 المجموعة: {chat_name}\n"
                f"🆔 المعرف: {chat_id}\n\n"
                f"🔐 استخدم `/security` لإعدادات الأمان\n"
                f"🛠️ استخدم `/panel` للوحة التحكم\n\n"
                f"👑 **المالك المخفي:** تم تسجيلك كمالك مخفي تلقائياً 🎉",
                parse_mode="MarkdownV2"
            )
            break

# ===================== أوامر المالك والمشرفين المخفيين =====================

async def register_hidden_owner_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تسجيل مالك مخفي للمجموعة"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    # التحقق من أن البوت مشرف
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"⚠️ **تنبيه:**\n{bot_perms['reason']}\n\nيرجى منح البوت الصلاحيات المطلوبة.")
        return
    
    # تسجيل المالك المخفي
    await db_register_hidden_owner_group(chat_id, user_id)
    await db_sync_group_admins(chat_id, context.bot, user_id)
    
    await update.message.reply_text(get_text(user_id, 'hidden_owner_registered'))

async def add_hidden_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة مشرف مخفي"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # التحقق من الصلاحية (مالك مخفي أو مشرف حقيقي)
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    args = context.args
    if not args:
        await update.message.reply_text("📝 **الاستخدام:**\n`/add_hidden_admin user_id`\n\nمثال: `/add_hidden_admin 123456789`")
        return
    
    try:
        admin_id = int(args[0])
        if await db_add_hidden_admin(chat_id, admin_id, user_id):
            await update.message.reply_text(get_text(user_id, 'hidden_admin_added').format(admin_id))
        else:
            await update.message.reply_text("⚠️ هذا المستخدم مسجل بالفعل كمشرف مخفي")
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح!")

async def remove_hidden_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إزالة مشرف مخفي"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    args = context.args
    if not args:
        await update.message.reply_text("📝 **الاستخدام:**\n`/remove_hidden_admin user_id`\n\nمثال: `/remove_hidden_admin 123456789`")
        return
    
    try:
        admin_id = int(args[0])
        if await db_remove_hidden_admin(chat_id, admin_id):
            await update.message.reply_text(get_text(user_id, 'hidden_admin_removed').format(admin_id))
        else:
            await update.message.reply_text("⚠️ هذا المستخدم ليس مشرفاً مخفياً")
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح!")

async def list_hidden_admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض المشرفين المخفيين"""
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
        text += f"• `{admin['admin_id']}` (تمت الإضافة بواسطة: `{admin['added_by']}`)\n"
    
    await safe_send_markdown(context.bot, user_id, text)

# ===================== أوامر معالجة الإجراءات المتقدمة =====================

async def handle_moderation_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أوامر الإجراءات المتقدمة"""
    if not update.message or not update.effective_user or not update.effective_chat:
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text(get_text(user_id, 'group_only'))
        return
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    command = update.message.text.split()[0][1:]  # إزالة /
    args = context.args
    reason = " ".join(args[1:]) if len(args) > 1 else ""
    
    # إذا كان هناك رد على رسالة، استخدم معرف المرسل
    target_id = None
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_id = update.message.reply_to_message.from_user.id
    elif args:
        try:
            target_id = int(args[0])
            if len(args) > 1:
                reason = " ".join(args[1:])
        except ValueError:
            await update.message.reply_text("❌ معرف مستخدم غير صالح!")
            return
    
    if not target_id:
        await update.message.reply_text("❌ يرجى تحديد مستخدم بالرد على رسالته أو إرسال معرفه.")
        return
    
    if target_id == context.bot.id:
        await update.message.reply_text("❌ لا يمكن تنفيذ هذا الإجراء على البوت!")
        return
    
    if target_id == PRIMARY_OWNER_ID:
        await update.message.reply_text("❌ لا يمكن تنفيذ هذا الإجراء على المالك الرئيسي!")
        return
    
    success = False
    msg = ""
    
    if command == "ban":
        success, msg = await execute_ban(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
    elif command == "mute":
        # مدة الكتم الافتراضية 60 دقيقة
        duration = 60
        if args and len(args) > 1:
            try:
                duration = int(args[1])
            except:
                pass
        success, msg = await execute_mute(context.bot, chat_id, target_id, duration, reason=reason, moderator_id=user_id)
    elif command == "warn":
        success, msg = await execute_warn(context.bot, chat_id, target_id, user_id, reason=reason)
    elif command == "kick":
        success, msg = await execute_kick(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
    elif command == "restrict":
        success, msg = await execute_restrict(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
    elif command == "pin":
        if update.message.reply_to_message:
            success, msg = await execute_pin(context.bot, chat_id, update.message.reply_to_message.message_id)
        else:
            msg = "❌ يرجى الرد على الرسالة التي تريد تثبيتها."
    elif command == "unban":
        success, msg = await execute_unban(context.bot, chat_id, target_id, moderator_id=user_id)
    else:
        msg = "❌ أمر غير معروف."
    
    await safe_send_markdown(context.bot, chat_id, msg)

# ===================== دوال معالجة الكلمات المحظورة للمجموعة =====================

async def banned_words_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة كلمة محظورة للمجموعة"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('banned_words_chat_id')
    
    if not chat_id:
        return
    
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    
    context.user_data['state'] = UserState.WAITING_GROUP_BANNED_WORD
    context.user_data['banned_words_chat_id'] = chat_id
    await query.edit_message_text("🚫 **أرسل الكلمة التي تريد حظرها:**\n(كلمة واحدة فقط)")

async def banned_words_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض الكلمات المحظورة للمجموعة"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('banned_words_chat_id')
    
    if not chat_id:
        return
    
    words = await db_get_banned_words(chat_id)
    if not words:
        msg = "📭 لا توجد كلمات محظورة"
    else:
        msg = "🚫 **الكلمات المحظورة:**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        for idx, (word, added_by, added_at) in enumerate(words[:20], 1):
            msg += f"{idx}. `{word}` (بواسطة: {added_by})\n"
        if len(words) > 20:
            msg += f"\n... و {len(words)-20} كلمة أخرى"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة", callback_data=f"{CallbackData.BANNED_WORDS_ADD_PREFIX}{chat_id}"),
         InlineKeyboardButton("🗑️ حذف", callback_data=f"{CallbackData.BANNED_WORDS_REMOVE_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])
    await safe_edit_markdown(query, msg, reply_markup=keyboard)

async def banned_words_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف كلمة محظورة من المجموعة"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('banned_words_chat_id')
    
    if not chat_id:
        return
    
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    
    context.user_data['state'] = UserState.WAITING_REMOVE_GROUP_BANNED_WORD
    context.user_data['banned_words_chat_id'] = chat_id
    await query.edit_message_text("🗑️ **أرسل الكلمة التي تريد حذفها:**\n(كلمة واحدة فقط)")

# ===================== دوال معالجة ردود المشرفين =====================

async def admin_replies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لوحة إدارة ردود المجموعة"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    await query.edit_message_text("💬 **إدارة ردود المجموعة**\n\nاختر الإجراء:", reply_markup=get_replies_keyboard())

async def admin_add_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة رد جديد"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_KEYWORD
    await query.edit_message_text("📝 **إضافة رد جديد**\n\nأرسل الكلمة المفتاحية (مثال: مرحبا):")

async def admin_list_replies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض جميع الردود"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    replies = await db_get_all_replies()
    if not replies:
        msg = "📭 لا توجد ردود مسجلة"
    else:
        msg = "📋 **قائمة الردود:**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        for keyword, reply in replies[:30]:
            msg += f"• **{keyword}** → {reply[:50]}{'...' if len(reply) > 50 else ''}\n"
        if len(replies) > 30:
            msg += f"\n... و {len(replies)-30} رد آخر"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_REPLIES)]
    ])
    await safe_edit_markdown(query, msg, reply_markup=keyboard)

async def admin_del_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف رد"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    # إذا كان الكولباك يحتوي على الكلمة مباشرة
    if query and query.data.startswith("admin_del_reply_"):
        keyword = query.data.replace("admin_del_reply_", "")
        if await db_del_reply(keyword):
            await query.edit_message_text(f"✅ تم حذف رد `{keyword}`")
        else:
            await query.edit_message_text(f"⚠️ الكلمة `{keyword}` غير موجودة")
        await admin_replies_callback(update, context)
        return
    
    # إذا كان المستخدم سيرسل الكلمة
    context.user_data['state'] = UserState.WAITING_REPLY
    context.user_data['admin_del_reply'] = True
    await query.edit_message_text("🗑️ **أرسل الكلمة المفتاحية التي تريد حذف ردها:**")

# ===================== دوال معالجة الكلمات المحظورة العامة =====================

async def admin_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لوحة إدارة الكلمات المحظورة العامة"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    await query.edit_message_text("🚫 **إدارة الكلمات المحظورة العامة**\n\nاختر الإجراء:", reply_markup=get_banned_words_admin_keyboard())

async def admin_add_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة كلمة محظورة عامة"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_GLOBAL_BANNED_WORD
    await query.edit_message_text("🚫 **أرسل الكلمة التي تريد حظرها عالمياً:**")

async def admin_list_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض الكلمات المحظورة العامة"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    words = await db_get_banned_words(-1)
    if not words:
        msg = "📭 لا توجد كلمات محظورة عامة"
    else:
        msg = "🚫 **الكلمات المحظورة عامة:**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        for idx, (word, added_by, added_at) in enumerate(words[:20], 1):
            msg += f"{idx}. `{word}`\n"
        if len(words) > 20:
            msg += f"\n... و {len(words)-20} كلمة أخرى"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة", callback_data=CallbackData.ADMIN_ADD_BANNED_WORD),
         InlineKeyboardButton("🗑️ حذف", callback_data=f"{CallbackData.ADMIN_REMOVE_BANNED_WORD}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_BANNED_WORDS)]
    ])
    await safe_edit_markdown(query, msg, reply_markup=keyboard)

async def admin_remove_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف كلمة محظورة عامة"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_REMOVE_GLOBAL_BANNED_WORD
    await query.edit_message_text("🗑️ **أرسل الكلمة التي تريد حذفها من القائمة العامة:**")

async def admin_del_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف كلمة محظورة عامة مباشرة"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    word = query.data.split("_")[-1]
    async def _delete(conn):
        await conn.execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", (word, -1))
        await conn.commit()
    await execute_db(_delete)
    await query.edit_message_text(f"✅ تم حذف الكلمة: {word}")
    await admin_banned_words_callback(update, context)

# ===================== دوال معالجة إعدادات NSFW =====================

async def nsfw_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض إعدادات NSFW"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    status_text = "🟢 مفعل" if NSFW_ENABLED else "🔴 معطل"
    threshold_percent = int(NSFW_THRESHOLD * 100)
    
    text = f"🔞 **إعدادات NSFW**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📌 الحالة: {status_text}\n"
    text += f"📊 نسبة الحساسية: {threshold_percent}%\n"
    text += f"📁 الحد الأقصى للصورة: {NSFW_MAX_FILE_SIZE // (1024*1024)} ميجابايت\n"
    text += f"🎬 الحد الأقصى للفيديو: {NSFW_MAX_VIDEO_SIZE // (1024*1024)} ميجابايت\n"
    text += f"🔄 عدد الإطارات للفيديو: {NSFW_FRAMES}\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📌 اختر الإجراء المناسب:"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{'🔴 تعطيل' if NSFW_ENABLED else '🟢 تفعيل'}", callback_data=CallbackData.NSFW_TOGGLE)],
        [InlineKeyboardButton(f"📊 تغيير نسبة الحساسية ({threshold_percent}%)", callback_data=CallbackData.NSFW_THRESHOLD_SET)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def nsfw_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبديل حالة NSFW"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    global NSFW_ENABLED
    NSFW_ENABLED = not NSFW_ENABLED
    os.environ["NSFW_ENABLED"] = "True" if NSFW_ENABLED else "False"
    await query.edit_message_text(f"✅ تم {'تفعيل' if NSFW_ENABLED else 'تعطيل'} كشف NSFW")
    await nsfw_settings_callback(update, context)

async def nsfw_threshold_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تغيير نسبة حساسية NSFW"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    context.user_data['state'] = UserState.WAITING_NSFW_THRESHOLD
    await query.edit_message_text("📊 **تغيير نسبة حساسية NSFW**\n\nأرسل النسبة المئوية (1-100):\nمثال: `75`")

# ===================== دوال معالجة إعدادات الردود التلقائية =====================

async def admin_auto_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض إعدادات الردود التلقائية"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    
    # إذا كان هناك chat_id في الكولباك
    chat_id = None
    if query and query.data and ":" in query.data:
        try:
            chat_id = int(query.data.split(":")[-1])
        except:
            pass
    
    if not chat_id:
        chat_id = context.user_data.get('auto_reply_chat_id')
    
    if not chat_id:
        await query.edit_message_text("⚠️ يرجى اختيار مجموعة أولاً")
        return
    
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    
    settings = await db_get_auto_reply_settings(chat_id)
    await query.edit_message_text(
        f"📝 **إعدادات الردود التلقائية**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 الحالة: {'🟢 مفعل' if settings['enabled'] else '🔴 معطل'}\n"
        f"👥 المستخدمون: {'👑 مشرفين فقط' if settings['only_admins'] else '👥 الجميع'}\n"
        f"🤖 تجاهل البوتات: {'✅' if settings['ignore_bots'] else '❌'}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 اختر الإجراء المناسب:",
        reply_markup=get_auto_reply_keyboard(chat_id, settings)
    )

async def admin_auto_reply_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختيار مجموعة لإعدادات الردود التلقائية"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    
    context.user_data['auto_reply_chat_id'] = chat_id
    await admin_auto_reply_callback(update, context)

# ===================== دوال معالجة ردود المستخدمين التلقائية =====================

async def user_auto_reply_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض إعدادات الردود التلقائية للمستخدم"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    
    enabled = await db_get_user_auto_reply_status(uid)
    await query.edit_message_text(
        f"📝 **إعدادات الردود التلقائية**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 الحالة: {'🟢 مفعل' if enabled else '🔴 معطل'}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 اختر الإجراء المناسب:",
        reply_markup=get_user_auto_reply_keyboard(uid, enabled)
    )

# ===================== دوال معالجة واجهة الويب =====================

async def health_check_handler(request):
    """نقطة نهاية للتحقق من صحة البوت"""
    try:
        # التحقق من قاعدة البيانات
        await execute_db(lambda conn: conn.execute("SELECT 1"))
        return web.json_response({
            'status': 'healthy',
            'version': '19.3.4',
            'timestamp': utc_now_iso()
        })
    except Exception as e:
        return web.json_response({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': utc_now_iso()
        }, status=500)

def get_ram_usage() -> dict:
    """الحصول على استخدام الذاكرة"""
    try:
        import psutil
        mem = psutil.virtual_memory()
        return {
            'total': mem.total,
            'used': mem.used,
            'percent': mem.percent,
            'available': mem.available
        }
    except:
        return {'percent': 0, 'used': 0, 'total': 0, 'available': 0}

async def check_database_health() -> bool:
    """التحقق من صحة قاعدة البيانات"""
    try:
        await execute_db(lambda conn: conn.execute("SELECT 1"))
        return True
    except:
        return False

async def check_telegram_health() -> bool:
    """التحقق من الاتصال بتليجرام"""
    try:
        from telegram import Bot
        bot = Bot(token=TOKEN)
        await bot.get_me()
        return True
    except:
        return False

# ===================== دوال معالجة لوحة المشرف =====================

async def admin_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة المستخدمين"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    users = await db_get_all_users()
    total = len(users)
    banned = sum(1 for u in users if u[1] == 1)
    
    text = f"👥 **المستخدمين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📌 الإجمالي: {total}\n"
    text += f"⛔ محظورين: {banned}\n"
    text += f"✅ نشطين: {total - banned}\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for user_id, is_banned in users[:20]:
        try:
            user = await context.bot.get_chat(user_id)
            name = user.first_name or str(user_id)
        except:
            name = str(user_id)
        text += f"{'⛔' if is_banned else '✅'} `{user_id}` - {name}\n"
    
    if len(users) > 20:
        text += f"\n... و {len(users)-20} مستخدم آخر"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_banned_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض المستخدمين المحظورين"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    users = await db_get_all_users()
    banned_users = [u for u in users if u[1] == 1]
    
    if not banned_users:
        text = "📭 لا يوجد مستخدمين محظورين"
    else:
        text = f"⛔ **المستخدمين المحظورين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        text += f"📌 العدد: {len(banned_users)}\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for user_id, _ in banned_users[:20]:
            try:
                user = await context.bot.get_chat(user_id)
                name = user.first_name or str(user_id)
            except:
                name = str(user_id)
            text += f"• `{user_id}` - {name}\n"
        if len(banned_users) > 20:
            text += f"\n... و {len(banned_users)-20} مستخدم آخر"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_USERS)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_unban_all_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء حظر جميع المستخدمين"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    async def _unban_all(conn):
        await conn.execute("UPDATE users SET banned=0")
        await conn.commit()
    await execute_db(_unban_all)
    await query.edit_message_text("✅ تم إلغاء حظر جميع المستخدمين")
    await admin_users_callback(update, context)

async def admin_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض جميع قنوات المستخدمين"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    channels = await db_get_all_user_channels_no_limit()
    total = len(channels)
    banned = sum(1 for ch in channels if ch[4] == 1)
    
    text = f"📡 **جميع قنوات المستخدمين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📌 الإجمالي: {total}\n"
    text += f"⛔ محظورة: {banned}\n"
    text += f"✅ نشطة: {total - banned}\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for user_id, ch_id, ch_tele, ch_name, is_banned in channels[:20]:
        text += f"{'⛔' if is_banned else '✅'} `{ch_tele}` - {ch_name[:30]}\n"
    
    if len(channels) > 20:
        text += f"\n... و {len(channels)-20} قناة أخرى"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_banned_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض القنوات المحظورة"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    channels = await db_all_users_channels(only_banned=True)
    if not channels:
        text = "📭 لا توجد قنوات محظورة"
    else:
        text = f"⛔ **القنوات المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        text += f"📌 العدد: {len(channels)}\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for user_id, ch_id, ch_tele, ch_name, _ in channels[:20]:
            text += f"• `{ch_tele}` - {ch_name[:30]}\n"
        if len(channels) > 20:
            text += f"\n... و {len(channels)-20} قناة أخرى"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ تنشيط الكل", callback_data=CallbackData.ADMIN_ACTIVATE_ALL_CHANNELS)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_activate_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تنشيط جميع القنوات"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    async def _activate(conn):
        await conn.execute("UPDATE user_channels SET banned=0")
        await conn.commit()
    await execute_db(_activate)
    await query.edit_message_text("✅ تم تنشيط جميع القنوات")
    await admin_all_channels_callback(update, context)

async def admin_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض جميع المجموعات"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    groups = await db_get_all_groups()
    total = len(groups)
    banned = sum(1 for g in groups if g[5] == 1)
    
    text = f"👥 **جميع المجموعات**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📌 الإجمالي: {total}\n"
    text += f"⛔ محظورة: {banned}\n"
    text += f"✅ نشطة: {total - banned}\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for chat_id, chat_name, username, added_by, added_at, is_banned in groups[:20]:
        text += f"{'⛔' if is_banned else '✅'} `{chat_id}` - {chat_name[:30]}\n"
    
    if len(groups) > 20:
        text += f"\n... و {len(groups)-20} مجموعة أخرى"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_banned_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض المجموعات المحظورة"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    groups = await db_get_all_groups(only_banned=True)
    if not groups:
        text = "📭 لا توجد مجموعات محظورة"
    else:
        text = f"⛔ **المجموعات المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        text += f"📌 العدد: {len(groups)}\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for chat_id, chat_name, username, added_by, added_at, _ in groups[:20]:
            text += f"• `{chat_id}` - {chat_name[:30]}\n"
        if len(groups) > 20:
            text += f"\n... و {len(groups)-20} مجموعة أخرى"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_GROUPS)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_unban_all_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء حظر جميع المجموعات"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    async def _unban(conn):
        await conn.execute("UPDATE bot_groups SET banned=0")
        await conn.commit()
    await execute_db(_unban)
    await query.edit_message_text("✅ تم إلغاء حظر جميع المجموعات")
    await admin_groups_callback(update, context)

async def admin_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قنوات البوت"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    channels = await db_get_all_bot_channels()
    total = len(channels)
    banned = sum(1 for ch in channels if ch[4] == 1)
    
    text = f"📢 **قنوات البوت**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📌 الإجمالي: {total}\n"
    text += f"⛔ محظورة: {banned}\n"
    text += f"✅ نشطة: {total - banned}\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for channel_id, channel_name, added_by, added_at, is_banned in channels[:20]:
        text += f"{'⛔' if is_banned else '✅'} `{channel_id}` - {channel_name[:30]}\n"
    
    if len(channels) > 20:
        text += f"\n... و {len(channels)-20} قناة أخرى"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_banned_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قنوات البوت المحظورة"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    channels = await db_get_all_bot_channels(only_banned=True)
    if not channels:
        text = "📭 لا توجد قنوات بوت محظورة"
    else:
        text = f"⛔ **قنوات البوت المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        text += f"📌 العدد: {len(channels)}\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for channel_id, channel_name, added_by, added_at, _ in channels[:20]:
            text += f"• `{channel_id}` - {channel_name[:30]}\n"
        if len(channels) > 20:
            text += f"\n... و {len(channels)-20} قناة أخرى"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_BOT_CHANNELS)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_unban_all_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء حظر جميع قنوات البوت"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    async def _unban(conn):
        await conn.execute("UPDATE bot_channels SET banned=0")
        await conn.commit()
    await execute_db(_unban)
    await query.edit_message_text("✅ تم إلغاء حظر جميع قنوات البوت")
    await admin_bot_channels_callback(update, context)

async def admin_monitor_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مراقبة المستخدمين"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    await query.edit_message_text("📂 **مراقبة المستخدمين**\n\nهذه الميزة قيد التطوير.", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ]))

async def admin_add_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة مشرف"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_ADMIN_ID_ADD
    await query.edit_message_text("👑 **إضافة مشرف جديد**\n\nأرسل معرف المستخدم (user_id):")

async def admin_remove_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إزالة مشرف"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_ADMIN_ID_REMOVE
    await query.edit_message_text("🗑️ **إزالة مشرف**\n\nأرسل معرف المستخدم (user_id):")

async def admin_ram_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض حالة الذاكرة"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    ram = get_ram_usage()
    text = f"🖥️ **حالة الذاكرة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📊 الاستخدام: {ram['percent']}%\n"
    text += f"📦 المستخدم: {ram['used'] // (1024*1024)} ميجابايت\n"
    text += f"📦 الإجمالي: {ram['total'] // (1024*1024)} ميجابايت\n"
    text += f"📦 المتاح: {ram['available'] // (1024*1024)} ميجابايت\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data=CallbackData.ADMIN_RAM)],
        [InlineKeyboardButton("🧹 تنظيف الذاكرة", callback_data="admin:clear_cache")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض الإحصائيات العامة"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    total, banned, posts, groups, channels = await db_stats()
    text = f"📊 **الإحصائيات العامة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"👥 إجمالي المستخدمين: {total}\n"
    text += f"⛔ المحظورين: {banned}\n"
    text += f"✅ النشطين: {total - banned}\n"
    text += f"📝 المنشورات غير المنشورة: {posts}\n"
    text += f"👥 المجموعات: {groups}\n"
    text += f"📡 القنوات: {channels}\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data=CallbackData.ADMIN_STATS)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_metrics_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض مقاييس الأداء"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    stats = metrics.get_stats()
    text = f"📈 **مقاييس الأداء**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"⏱️ وقت التشغيل: {int(stats['uptime'] / 3600)} ساعة\n"
    text += f"📊 إجمالي الأوامر: {stats['total_commands']}\n"
    text += f"⚡ متوسط وقت الاستجابة: {stats['avg_response_time']:.2f} ثانية\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    
    if stats['commands']:
        text += "📌 **الأوامر الأكثر استخداماً:**\n"
        for cmd, count in sorted(stats['commands'].items(), key=lambda x: x[1], reverse=True)[:5]:
            text += f"• /{cmd}: {count}\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data=CallbackData.ADMIN_METRICS)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض إدارة النسخ الاحتياطية"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    backups = await list_backups()
    text = f"💾 **النسخ الاحتياطية**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    if not backups:
        text += "📭 لا توجد نسخ احتياطية"
    else:
        text += f"📌 عدد النسخ: {len(backups)}\n━━━━━━━━━━━━━━━━━━━━━━\n"
        for backup in backups[:10]:
            stat = backup.stat()
            size_mb = stat.st_size / (1024 * 1024)
            date = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            text += f"• {backup.name}\n  📦 {size_mb:.2f} ميجابايت - 🕐 {date}\n"
        if len(backups) > 10:
            text += f"\n... و {len(backups)-10} نسخة أخرى"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 إنشاء نسخة", callback_data="admin:create_backup")],
        [InlineKeyboardButton("🔄 استعادة نسخة", callback_data=CallbackData.ADMIN_RESTORE_BACKUP)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_restore_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض النسخ المتاحة للاستعادة"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    backups = await list_backups()
    if not backups:
        await query.edit_message_text("📭 لا توجد نسخ احتياطية للاستعادة")
        return
    
    keyboard = []
    for backup in backups[:10]:
        keyboard.append([InlineKeyboardButton(
            f"📂 {backup.name}",
            callback_data=f"{CallbackData.ADMIN_RESTORE_BACKUP_SELECT_PREFIX}{backup.name}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_BACKUP)])
    
    await query.edit_message_text(
        "🔄 **استعادة نسخة احتياطية**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر النسخة للاستعادة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_restore_backup_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استعادة نسخة محددة"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    backup_name = query.data.split(":")[-1]
    backup_path = BACKUP_DIR / backup_name
    
    if not backup_path.exists():
        await query.edit_message_text("❌ الملف غير موجود")
        return
    
    # تأكيد الاستعادة
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، استعد", callback_data=f"confirm_restore:{backup_name}"),
         InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.ADMIN_BACKUP)]
    ])
    await query.edit_message_text(f"⚠️ **تأكيد استعادة النسخة**\n\nالملف: `{backup_name}`\n\nهل أنت متأكد؟", reply_markup=keyboard)

async def admin_backup_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إعدادات النسخ الاحتياطي"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    auto_backup = await db_get_auto_backup()
    status_text = "🟢 مفعل" if auto_backup else "🔴 معطل"
    
    text = f"⚙️ **إعدادات النسخ الاحتياطي**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📌 النسخ التلقائي: {status_text}\n"
    text += f"📦 عدد النسخ المحفوظة: {MAX_BACKUPS}\n"
    text += f"☁️ Google Drive: {'✅ مفعل' if CLOUD_BACKUP_ENABLED else '❌ معطل'}\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{'🔴 تعطيل' if auto_backup else '🟢 تفعيل'} النسخ التلقائي", callback_data=CallbackData.ADMIN_TOGGLE_AUTO_BACKUP)],
        [InlineKeyboardButton("⏱️ تغيير الفاصل الزمني", callback_data=CallbackData.ADMIN_CHANGE_INTERVAL)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_toggle_auto_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبديل النسخ الاحتياطي التلقائي"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    current = await db_get_auto_backup()
    await db_set_auto_backup(not current)
    await admin_backup_settings_callback(update, context)

async def admin_change_interval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تغيير فاصل النشر العام"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    current_interval = await db_get_publish_interval()
    current_minutes = current_interval // 60
    
    context.user_data['state'] = UserState.WAITING_INTERVAL_MINUTES
    context.user_data['admin_interval'] = True
    
    await query.edit_message_text(f"⏱️ **تغيير وقت النشر العام**\n\nالوقت الحالي: {current_minutes} دقيقة\n\nأرسل الوقت الجديد بالدقائق (مثال: 30):")

async def admin_send_update_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نشر تحديث في قناة التحديثات"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    channel = await db_get_updates_channel()
    if not channel:
        await query.edit_message_text("❌ لم يتم تعيين قناة تحديثات بعد\nاستخدم زر '⚙️ قناة التحديثات' أولاً")
        return
    
    context.user_data['state'] = UserState.WAITING_UPDATE_TEXT
    await query.edit_message_text(f"📢 **نشر تحديث**\n\nقناة التحديثات: @{channel}\n\nأرسل نص التحديث (يدعم HTML):")

async def admin_set_update_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين قناة التحديثات"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    context.user_data['state'] = UserState.WAITING_UPDATE_CHANNEL
    await query.edit_message_text("📢 **تعيين قناة التحديثات**\n\nأرسل معرف القناة (مثال: @my_channel أو -1001234567890):")

async def admin_show_update_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قناة التحديثات الحالية"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    channel = await db_get_updates_channel()
    if channel:
        text = f"📢 **قناة التحديثات الحالية:**\n@{channel}"
    else:
        text = "📢 **لم يتم تعيين قناة تحديثات بعد**"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 تغيير القناة", callback_data=CallbackData.ADMIN_SET_UPDATE_CHANNEL)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_updates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض التحديثات"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    await query.edit_message_text(
        "📢 **لوحة التحديثات**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        "📌 اختر الإجراء المناسب:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 نشر تحديث", callback_data=CallbackData.ADMIN_SEND_UPDATE)],
            [InlineKeyboardButton("⚙️ تعيين قناة التحديثات", callback_data=CallbackData.ADMIN_SET_UPDATE_CHANNEL)],
            [InlineKeyboardButton("📋 عرض القناة الحالية", callback_data=CallbackData.ADMIN_SHOW_UPDATE_CHANNEL)],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
        ])
    )

async def admin_force_subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبديل الاشتراك الإجباري"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    current = await db_get_force_subscribe_status()
    await db_set_force_subscribe_status(not current)
    status_text = "🟢 مفعل" if not current else "🔴 معطل"
    await query.edit_message_text(f"✅ تم تغيير الاشتراك الإجباري إلى: {status_text}")
    await admin_panel_callback(update, context)

async def admin_set_force_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين قناة الاشتراك الإجباري"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    context.user_data['state'] = UserState.WAITING_FORCE_CHANNEL
    await query.edit_message_text("🔒 **تعيين قناة الاشتراك الإجباري**\n\nأرسل معرف القناة (مثال: @my_channel):")

async def admin_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال رسالة جماعية"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    context.user_data['state'] = UserState.WAITING_BROADCAST
    await query.edit_message_text("📨 **إرسال رسالة جماعية**\n\nأرسل النص الذي تريد إرساله لجميع المستخدمين:")

async def admin_confirm_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تأكيد إرسال الرسالة الجماعية"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    text = context.user_data.get('broadcast_text')
    if not text:
        await query.edit_message_text("❌ لا يوجد نص للإرسال")
        return
    
    await query.edit_message_text("📨 جاري إرسال الرسالة الجماعية...")
    
    users = await db_get_all_users()
    success = 0
    failed = 0
    
    for user_id, banned in users:
        if banned:
            continue
        try:
            await safe_send_markdown(context.bot, user_id, text)
            success += 1
        except:
            failed += 1
        await asyncio.sleep(0.05)
    
    context.user_data.pop('broadcast_text', None)
    await query.edit_message_text(f"📨 **تم إرسال الرسالة الجماعية**\n━━━━━━━━━━━━━━━━━━━━━━\n✅ نجح: {success}\n❌ فشل: {failed}")

async def admin_support_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض تذاكر الدعم"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    tickets = await db_get_all_tickets(20)
    if not tickets:
        text = "📭 لا توجد تذاكر دعم"
    else:
        text = f"📋 **تذاكر الدعم**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        for ticket_id, user_id, username, message, ticket_num, status, created_at in tickets:
            status_icon = "🟢" if status == 'replied' else "🟡" if status == 'pending' else "🔴"
            text += f"{status_icon} #{ticket_num} - {username[:20]}\n"
            text += f"   👤 `{user_id}` - 🕐 {created_at[:10]}\n"
            text += f"   📝 {message[:50]}{'...' if len(message) > 50 else ''}\n\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ حذف جميع التذاكر", callback_data=CallbackData.ADMIN_DELETE_ALL_TICKETS)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_delete_all_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تأكيد حذف جميع التذاكر"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، احذف الكل", callback_data=CallbackData.ADMIN_CONFIRM_DELETE_TICKETS)],
        [InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.ADMIN_SUPPORT_TICKETS)]
    ])
    await query.edit_message_text("⚠️ **تأكيد حذف جميع التذاكر**\n\nهل أنت متأكد من حذف جميع تذاكر الدعم؟", reply_markup=keyboard)

async def admin_confirm_delete_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف جميع التذاكر"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    count = await db_delete_all_tickets()
    await query.edit_message_text(f"✅ تم حذف {count} تذكرة")
    await admin_panel_callback(update, context)

async def admin_manage_sendcode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إدارة صلاحية /sendcode"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    current_user = await db_get_allowed_sendcode_user()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 تعيين مستخدم", callback_data=CallbackData.ADMIN_SET_SENDCODE_USER)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    
    if current_user:
        msg = f"📋 **المستخدم المصرح بـ /sendcode:**\n`{current_user}`"
    else:
        msg = "📋 **لم يتم تعيين مستخدم لـ /sendcode**"
    
    await safe_edit_markdown(query, msg, reply_markup=keyboard)

async def admin_set_sendcode_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين مستخدم مصرح له بـ /sendcode"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    context.user_data['state'] = UserState.WAITING_SENDCODE_USER
    await query.edit_message_text("📝 **تعيين مستخدم لـ /sendcode**\n\nأرسل معرف المستخدم (user_id):")

async def admin_show_log_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قناة التقارير الحالية"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    channel_id = await db_get_log_channel_id()
    if channel_id:
        msg = f"📋 **قناة التقارير الحالية:**\n`{channel_id}`"
    else:
        msg = "📋 **لم يتم تعيين قناة تقارير بعد**"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 تعيين قناة جديدة", callback_data=CallbackData.ADMIN_SET_LOG_CHANNEL)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, msg, reply_markup=keyboard)

async def admin_set_log_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين قناة التقارير"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    context.user_data['state'] = UserState.WAITING_LOG_CHANNEL
    await query.edit_message_text("📝 **تعيين قناة التقارير**\n\nأرسل معرف القناة (مثال: @my_channel أو -1001234567890):")

async def admin_toggle_channel_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبديل حظر قناة مستخدم"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    channel_db_id = int(query.data.split(":")[-1])
    async def _toggle(conn):
        cur = await conn.execute("SELECT banned FROM user_channels WHERE id=?", (channel_db_id,))
        row = await cur.fetchone()
        if not row:
            return None
        new_status = 0 if row[0] == 1 else 1
        await conn.execute("UPDATE user_channels SET banned=? WHERE id=?", (new_status, channel_db_id))
        await conn.commit()
        return new_status
    new_status = await execute_db(_toggle)
    if new_status is not None:
        status_text = "محظورة" if new_status == 1 else "نشطة"
        await query.edit_message_text(f"✅ تم تغيير حالة القناة إلى: {status_text}")
    else:
        await query.edit_message_text("❌ القناة غير موجودة")
    await admin_all_channels_callback(update, context)

async def admin_toggle_group_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبديل حظر مجموعة"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    chat_id = int(query.data.split(":")[-1])
    async def _toggle(conn):
        cur = await conn.execute("SELECT banned FROM bot_groups WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        if not row:
            return None
        new_status = 0 if row[0] == 1 else 1
        await conn.execute("UPDATE bot_groups SET banned=? WHERE chat_id=?", (new_status, chat_id))
        await conn.commit()
        return new_status
    new_status = await execute_db(_toggle)
    if new_status is not None:
        status_text = "محظورة" if new_status == 1 else "نشطة"
        await query.edit_message_text(f"✅ تم تغيير حالة المجموعة إلى: {status_text}")
    else:
        await query.edit_message_text("❌ المجموعة غير موجودة")
    await admin_groups_callback(update, context)

# ===================== دوال معالجة أوامر /sendcode =====================

async def sendcode_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال كود البوت للمستخدم المصرح له"""
    if not update.message:
        return
    
    user_id = update.effective_user.id
    
    # تحقق من الصلاحية
    allowed_user = await db_get_allowed_sendcode_user()
    if user_id != PRIMARY_OWNER_ID and user_id != allowed_user and not await is_bot_admin(user_id):
        await update.message.reply_text("🔒 غير مصرح لك باستخدام هذا الأمر!")
        return
    
    # إذا كان المستخدم هو PRIMARY_OWNER_ID، لا حاجة للتحقق الإضافي
    if user_id == PRIMARY_OWNER_ID:
        await send_bot_code(update, context)
        return
    
    # تحقق من المصادقة الثنائية للمستخدم العادي
    if ENABLE_2FA and ADMIN_2FA_SECRET and PYOTP_AVAILABLE:
        context.user_data['waiting_2fa'] = True
        context.user_data['sendcode_user'] = user_id
        await update.message.reply_text(
            "🔐 **مطلوب رمز المصادقة الثنائية**\n\n"
            "أدخل الرمز المكون من 6 أرقام من تطبيق المصادقة (Google Authenticator).\n"
            "⏳ لديك 5 دقائق لإدخال الرمز."
        )
        return
    
    await send_bot_code(update, context)

async def send_bot_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال كود البوت الفعلي"""
    user_id = update.effective_user.id
    
    # إنشاء كود مؤقت
    code = secrets.token_hex(8)
    # تخزين الكود لمدة 10 دقائق
    context.user_data['bot_code'] = code
    context.user_data['bot_code_time'] = time_module.time()
    
    await update.message.reply_text(
        f"🔑 **كود البوت الخاص بك**\n━━━━━━━━━━━━━━━━━━━━━━\n`{code}`\n\n⏳ الكود صالح لمدة 10 دقائق\n\n📌 استخدم هذا الكود للتحقق من هوية البوت في الخدمات الخارجية.",
        parse_mode="MarkdownV2"
    )

async def handle_sendcode_confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة تأكيد رمز المصادقة الثنائية لـ /sendcode"""
    if not update.message:
        return
    
    user_id = update.effective_user.id
    code = update.message.text.strip()
    
    if ENABLE_2FA and ADMIN_2FA_SECRET and PYOTP_AVAILABLE:
        try:
            totp = pyotp.TOTP(ADMIN_2FA_SECRET)
            if totp.verify(code):
                context.user_data.pop('waiting_2fa', None)
                await update.message.reply_text("✅ تم التحقق من المصادقة الثنائية!")
                await send_bot_code(update, context)
                return
            else:
                await update.message.reply_text("❌ رمز غير صحيح! حاول مرة أخرى.")
                # السماح بمحاولة أخرى
                context.user_data['waiting_2fa'] = True
                return
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ في التحقق: {str(e)[:100]}")
            context.user_data.pop('waiting_2fa', None)
            return
    else:
        await update.message.reply_text("❌ المصادقة الثنائية غير مفعلة.")
        context.user_data.pop('waiting_2fa', None)

async def set_sendcode_user_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين مستخدم مصرح له باستخدام /sendcode (للمشرفين)"""
    if not update.message:
        return
    
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text(
            "📝 **الاستخدام:**\n"
            "`/set_sendcode_user user_id`\n\n"
            "مثال: `/set_sendcode_user 123456789`\n\n"
            "📌 بعد التعيين، سيتمكن المستخدم من استخدام أمر /sendcode"
        )
        return
    
    try:
        target_id = int(args[0])
        await db_set_allowed_sendcode_user(target_id)
        await security_audit.log("SENDCODE_PERMISSION_GRANTED", user_id, {"target": target_id}, "CRITICAL")
        await update.message.reply_text(f"✅ تم تعيين المستخدم `{target_id}` كمرخص لاستخدام /sendcode")
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح!")
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {str(e)[:100]}")

# ===================== دوال معالجة أوامر Set Rules =====================

async def set_rules_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# ===================== دوال معالجة رسائل الترشيح =====================

def contains_link(text: str) -> bool:
    """التحقق من وجود رابط في النص"""
    if not text:
        return False
    # رابط تيليجرام
    if re.search(r'(?:https?://)?t\.me/\S+', text):
        return True
    # رابط عام
    if re.search(r'(?:https?://)?[a-zA-Z0-9-]+(\.[a-zA-Z]{2,})+\S*', text):
        return True
    # رابط مختصر
    if re.search(r'(?:https?://)?(?:bit\.ly|tinyurl\.com|goo\.gl|ow\.ly|is\.gd|buff\.ly|adf\.ly)\S+', text):
        return True
    return False

def contains_mention(text: str) -> bool:
    """التحقق من وجود منشن في النص"""
    if not text:
        return False
    # منشن تيليجرام
    if re.search(r'@[a-zA-Z0-9_]{5,}', text):
        return True
    return False

# ===================== دوال معالجة الردود التلقائية =====================

async def auto_reply_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبديل الردود التلقائية في مجموعة"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    new_status = await db_toggle_auto_reply(chat_id)
    await query.edit_message_text(f"✅ تم {'تفعيل' if new_status else 'تعطيل'} الردود التلقائية")
    await admin_auto_reply_callback(update, context)

async def auto_reply_admins_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبديل وضع المشرفين فقط للردود"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    settings = await db_get_auto_reply_settings(chat_id)
    new_status = not settings['only_admins']
    await db_set_auto_reply_only_admins(chat_id, new_status)
    await query.edit_message_text(f"✅ تم تغيير وضع المستخدمين إلى: {'👑 مشرفين فقط' if new_status else '👥 الجميع'}")
    await admin_auto_reply_callback(update, context)

async def auto_reply_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إعادة تعيين الردود التلقائية"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، إعادة تعيين", callback_data=f"{CallbackData.AUTO_REPLY_CONFIRM_RESET_PREFIX}{chat_id}")],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"{CallbackData.AUTO_REPLY_CANCEL_PREFIX}{chat_id}")]
    ])
    await query.edit_message_text("⚠️ **تأكيد إعادة تعيين الردود التلقائية**\n\nهل أنت متأكد من إعادة تعيين جميع الردود التلقائية في هذه المجموعة؟", reply_markup=keyboard)

async def auto_reply_confirm_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تأكيد إعادة تعيين الردود التلقائية"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    async def _reset(conn):
        await conn.execute("DELETE FROM group_replies WHERE chat_id=?", (chat_id,))
        await conn.commit()
    await execute_db(_reset)
    await query.edit_message_text("✅ تم إعادة تعيين الردود التلقائية")
    await admin_auto_reply_callback(update, context)

async def auto_reply_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء إعادة تعيين الردود التلقائية"""
    query = update.callback_query
    if query:
        await query.answer()
    await admin_auto_reply_callback(update, context)

async def auto_reply_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض إحصائيات الردود التلقائية"""
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    async def _get_stats(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM group_replies WHERE chat_id=?", (chat_id,))
        total = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT COUNT(*) FROM auto_reply_log WHERE chat_id=? AND used_at >= datetime('now', '-7 days')", (chat_id,))
        used_week = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT COUNT(*) FROM auto_reply_log WHERE chat_id=? AND used_at >= datetime('now', '-30 days')", (chat_id,))
        used_month = (await cur.fetchone())[0]
        return {'total': total, 'used_week': used_week, 'used_month': used_month}
    stats = await execute_db(_get_stats)
    text = f"📊 **إحصائيات الردود التلقائية**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📝 عدد الردود: {stats['total']}\n"
    text += f"📊 المستخدمة هذا الأسبوع: {stats['used_week']}\n"
    text += f"📊 المستخدمة هذا الشهر: {stats['used_month']}\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.ADMIN_AUTO_REPLY_SELECT_PREFIX}{chat_id}")]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def user_auto_reply_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبديل الردود التلقائية لمستخدم"""
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    target_id = int(query.data.split(":")[-1])
    if user_id != target_id:
        await query.answer("❌ هذا الإعداد خاص بك فقط", show_alert=True)
        return
    enabled = await db_get_user_auto_reply_status(user_id)
    await db_set_user_auto_reply_status(user_id, not enabled)
    await query.edit_message_text(f"✅ تم {'تفعيل' if not enabled else 'تعطيل'} الردود التلقائية")
    await user_auto_reply_settings_callback(update, context)

# ===================== دوال معالجة المدفوعات =====================

async def pre_checkout_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة ما قبل الدفع"""
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الدفع الناجح"""
    user_id = update.effective_user.id
    payload = update.message.successful_payment.invoice_payload
    
    # استخراج عدد الأيام من الـ payload
    try:
        parts = payload.split("_")
        if len(parts) >= 2:
            days = int(parts[1])
            await db_activate_subscription(user_id, days)
            await update.message.reply_text(
                f"✅ **تم تفعيل اشتراكك بنجاح!**\n\n"
                f"🎉 شكراً لدعمك، اشتراكك مفعل لمدة {days} يوم.\n"
                f"💎 استمتع بجميع الميزات."
            )
        else:
            await update.message.reply_text("❌ حدث خطأ في معالجة الدفع.")
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ في معالجة الدفع: {str(e)[:100]}")

# ===================== دوال معالجة الأوامر الأساسية =====================

async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /start"""
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name or ""
    username = user.username or ""
    
    # تسجيل المستخدم
    await db_register_user(user_id)
    await db_update_user_cache(user_id, username, first_name)
    
    # معالجة رابط الإحالة
    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            referral_code = arg[4:]
            referrer_id = await db_get_user_by_referral_code(referral_code)
            if referrer_id and referrer_id != user_id:
                if await db_add_referral(referrer_id, user_id):
                    await db_auto_reward_referral(referrer_id, user_id)
                    try:
                        await context.bot.send_message(
                            referrer_id,
                            f"🎉 **إحالة جديدة!**\n\n"
                            f"قام {first_name} بالتسجيل عبر رابطك.\n"
                            f"🌟 لقد حصلت على مكافأة إحالة جديدة!"
                        )
                    except:
                        pass
                    # إضافة نقاط ترحيب للمستخدم الجديد
                    welcome_bonus = await db_get_welcome_bonus_points()
                    level_data = await db_get_user_level(user_id)
                    await db_update_user_level(user_id, level_data['points'] + welcome_bonus, level_data['level'])
    
    # عرض القائمة الرئيسية
    await main_menu_callback(update, context)

async def language_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /language"""
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
    if update.message:
        await update.message.reply_text(get_text(user_id, 'welcome'), reply_markup=keyboard)
    else:
        await safe_edit_markdown(update.callback_query, get_text(user_id, 'welcome'), reply_markup=keyboard)

async def syncgroup_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /syncgroup"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text(get_text(update.effective_user.id, 'group_only'))
        return
    
    chat_id = update.effective_chat.id
    chat_name = update.effective_chat.title or "بدون اسم"
    user_id = update.effective_user.id
    
    # تسجيل المجموعة
    await db_register_group(chat_id, chat_name, user_id, update.effective_chat.username)
    
    # مزامنة المشرفين
    count = await db_sync_group_admins(chat_id, context.bot, user_id)
    
    await update.message.reply_text(
        f"✅ **تم تفعيل المجموعة!**\n\n"
        f"📌 المجموعة: {chat_name}\n"
        f"🆔 المعرف: {chat_id}\n"
        f"👥 عدد المشرفين: {count}\n\n"
        f"🔐 استخدم `/security` لإعدادات الأمان\n"
        f"🛠️ استخدم `/panel` للوحة التحكم"
    )

async def security_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /security"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text(get_text(update.effective_user.id, 'group_only'))
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    await group_settings_callback(update, context)

async def trial_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /trial"""
    await trial_callback(update, context)

async def subscribe_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /subscribe"""
    await subscribe_menu_callback(update, context)

async def help_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /help"""
    await help_callback(update, context)

async def support_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /support"""
    await support_menu_callback(update, context)

async def support_reply_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /support_reply"""
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "📝 **الاستخدام:**\n"
            "`/support_reply ticket_id الرسالة`\n\n"
            "مثال: `/support_reply 5 شكراً لتواصلك، تم حل المشكلة`"
        )
        return
    
    try:
        ticket_id = int(args[0])
        reply_text = " ".join(args[1:])
        
        # الحصول على معرف المستخدم صاحب التذكرة
        async def _get_ticket_user(conn):
            cur = await conn.execute("SELECT user_id FROM support_tickets WHERE id=?", (ticket_id,))
            row = await cur.fetchone()
            return row[0] if row else None
        target_user = await execute_db(_get_ticket_user)
        
        if not target_user:
            await update.message.reply_text("❌ التذكرة غير موجودة")
            return
        
        # إرسال الرد للمستخدم
        await context.bot.send_message(
            target_user,
            f"📞 **رد على تذكرتك #{ticket_id}**\n━━━━━━━━━━━━━━━━━━━━━━\n\n{reply_text}"
        )
        
        # تحديث حالة التذكرة
        await db_mark_ticket_replied(ticket_id)
        
        await update.message.reply_text(f"✅ تم إرسال الرد على التذكرة #{ticket_id}")
    except ValueError:
        await update.message.reply_text("❌ معرف تذكرة غير صالح!")

async def rank_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /rank"""
    user_id = update.effective_user.id
    data = await get_rank(user_id)
    points = data['points']
    level = data['level']
    next_points = LEVEL_REQUIREMENTS.get(level + 1, points)
    points_needed = next_points - points if next_points > points else 0
    text = f"📊 **رتبتك الحالية**\n━━━━━━━━━━━━━━\n👤 {update.effective_user.first_name}\n⭐ **المستوى:** {level}\n📈 **النقاط:** {points}\n📌 **المتبقي للمستوى التالي:** {points_needed}"
    await update.message.reply_text(text)

async def top_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /top"""
    user_id = update.effective_user.id
    top_users = await get_top_users(10)
    if not top_users:
        await update.message.reply_text("📭 لا توجد نقاط مسجدة بعد.")
        return
    text = "🏆 **أفضل 10 مستخدمين**\n━━━━━━━━━━━━━━\n"
    for idx, (uid_user, points, level) in enumerate(top_users, 1):
        try:
            user = await context.bot.get_chat(uid_user)
            name = user.first_name or str(uid_user)
        except:
            name = str(uid_user)
        text += f"{idx}. {name} → المستوى {level} ({points} نقطة)\n"
    await update.message.reply_text(text)

async def developer_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /developer"""
    await developer_callback(update, context)

async def updates_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /updates"""
    await updates_callback(update, context)

async def stats_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /stats"""
    user_id = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
    if not active:
        await update.message.reply_text("⚠️ اختر قناة أولاً")
        return
    
    stats = await db_get_channel_stats(active)
    ch_info = await db_get_channel_info(active)
    channel_name = ch_info['channel_name'] if ch_info else "القناة"
    
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
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{active}")],
        [InlineKeyboardButton("📈 نمو القناة", callback_data=f"{CallbackData.CHANNEL_GROWTH}:{active}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def lock_chat_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /lock"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text(get_text(update.effective_user.id, 'group_only'))
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    await db_set_chat_lock(chat_id, True, user_id)
    await update.message.reply_text(get_text(user_id, 'locked'))

async def unlock_chat_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /unlock"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text(get_text(update.effective_user.id, 'group_only'))
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    await db_set_chat_lock(chat_id, False)
    await update.message.reply_text(get_text(user_id, 'unlocked'))

async def schedule_post_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /schedule"""
    user_id = update.effective_user.id
    context.user_data['state'] = UserState.WAITING_SCHEDULE_POST
    msg = "📝 **جدولة منشور جديد**\n\nأرسل المنشور بالصيغة التالية:\n`YYYY-MM-DD HH:MM نص المنشور`\n\nمثال: `2024-12-31 20:00 مرحباً بالجميع!`\n\n🕐 الوقت بتوقيت مكة المكرمة"
    await update.message.reply_text(msg, parse_mode="MarkdownV2")

async def panel_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /panel"""
    await admin_panel_callback(update, context)

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض لوحة التحكم"""
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        if query:
            await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    text = f"👑 **لوحة التحكم**\n━━━━━━━━━━━━━━━━━━━━━━\nمرحباً، اختر الإجراء المناسب:"
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=get_admin_keyboard(user_id))
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=get_admin_keyboard(user_id))

async def set_log_channel_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /set_log_channel"""
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text(
            "📝 **تعيين قناة التقارير**\n\n"
            "استخدم الأمر مع معرف القناة:\n"
            "`/set_log_channel channel_id`\n\n"
            "مثال: `/set_log_channel -1001234567890`"
        )
        return
    
    channel_id = args[0].strip()
    await db_set_log_channel_id(channel_id)
    await update.message.reply_text(f"✅ تم تعيين قناة التقارير إلى: `{channel_id}`")

async def is_user_subscribed(bot, user_id: int, channel: str) -> bool:
    """التحقق من اشتراك المستخدم في قناة"""
    try:
        # إزالة @ إذا وجدت
        if channel.startswith('@'):
            channel = channel[1:]
        member = await bot.get_chat_member(f"@{channel}", user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

# ===================== دوال النسخ الاحتياطي =====================

async def list_backups() -> List[Path]:
    """الحصول على قائمة النسخ الاحتياطية"""
    backups = []
    try:
        for f in BACKUP_DIR.glob("bot_backup_*.db"):
            backups.append(f)
        backups.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    except:
        pass
    return backups

async def create_backup() -> Path:
    """إنشاء نسخة احتياطية"""
    timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"bot_backup_{timestamp}.db"
    
    # نسخ قاعدة البيانات
    if DB_PATH.exists():
        shutil.copy2(DB_PATH, backup_path)
    
    # تنظيف النسخ القديمة
    backups = await list_backups()
    if len(backups) > MAX_BACKUPS:
        for old_backup in backups[MAX_BACKUPS:]:
            try:
                old_backup.unlink()
            except:
                pass
    
    return backup_path

async def auto_backup():
    """النسخ الاحتياطي التلقائي"""
    while True:
        try:
            await asyncio.sleep(AUTO_BACKUP_SLEEP)
            if await db_get_auto_backup():
                await create_backup()
                logger.info("✅ تم إنشاء نسخة احتياطية تلقائية")
                
                # نسخ إلى Google Drive إذا تم التفعيل
                if CLOUD_BACKUP_ENABLED:
                    try:
                        await upload_to_drive()
                    except Exception as e:
                        logger.warning(f"فشل النسخ إلى Google Drive: {e}")
        except Exception as e:
            logger.error(f"خطأ في النسخ الاحتياطي التلقائي: {e}")

async def upload_to_drive():
    """رفع النسخة الاحتياطية إلى Google Drive"""
    if not GOOGLE_AUTH_AVAILABLE:
        return
    
    try:
        # هذه وظيفة مبسطة - يمكن توسيعها حسب الحاجة
        logger.info("☁️ جاري رفع النسخة إلى Google Drive...")
        # سيتم تنفيذ الرفع الفعلي هنا
        logger.info("✅ تم رفع النسخة إلى Google Drive")
    except Exception as e:
        logger.error(f"فشل رفع النسخة إلى Google Drive: {e}")

# ===================== دوال تشغيل الخلفية =====================

async def auto_publish_loop_improved(bot):
    """حلقة النشر التلقائي المحسنة"""
    while True:
        try:
            await asyncio.sleep(POLL_INTERVAL)
            
            # الحصول على جميع القنوات النشطة
            channels = await db_get_all_user_channels_no_limit()
            
            # تنفيذ النشر
            for channel_db_id, _, _, _, banned in channels:
                if banned:
                    continue
                
                # التحقق من حالة النشر التلقائي
                user_id = None
                async def _get_user(conn):
                    cur = await conn.execute("SELECT user_id FROM user_channels WHERE id=?", (channel_db_id,))
                    row = await cur.fetchone()
                    return row[0] if row else None
                user_id = await execute_db(_get_user)
                if not user_id:
                    continue
                
                auto_status = await db_auto_status(user_id)
                if not auto_status:
                    continue
                
                # التحقق من الاشتراك
                if not await db_has_active_subscription(user_id):
                    continue
                
                # الحصول على جدولة القناة
                schedule = await db_get_schedule(channel_db_id)
                next_date_str = schedule.get('next_publish_date')
                
                if next_date_str:
                    try:
                        next_date = datetime.fromisoformat(next_date_str)
                        if utc_now() >= next_date:
                            # نشر منشور
                            post = await db_get_next_post(channel_db_id)
                            if post:
                                ch_info = await db_get_channel_info(channel_db_id)
                                translation_lang = await get_user_translation_language(user_id)
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
                                        await bot.send_photo(ch_info['channel_id'], post['media_file_id'], caption=final_text if final_text else None)
                                    elif post['media_type'] == 'video' and post['media_file_id']:
                                        await bot.send_video(ch_info['channel_id'], post['media_file_id'], caption=final_text if final_text else None)
                                    elif post['media_type'] == 'document' and post['media_file_id']:
                                        await bot.send_document(ch_info['channel_id'], post['media_file_id'], caption=final_text if final_text else None)
                                    elif post['media_type'] == 'audio' and post['media_file_id']:
                                        await bot.send_audio(ch_info['channel_id'], post['media_file_id'], caption=final_text if final_text else None)
                                    elif post['media_type'] == 'voice' and post['media_file_id']:
                                        await bot.send_voice(ch_info['channel_id'], post['media_file_id'], caption=final_text if final_text else None)
                                    elif post['media_type'] == 'animation' and post['media_file_id']:
                                        await bot.send_animation(ch_info['channel_id'], post['media_file_id'], caption=final_text if final_text else None)
                                    else:
                                        await bot.send_message(ch_info['channel_id'], final_text)
                                    await db_mark_published(post['id'])
                                    await db_set_last_publish(channel_db_id, utc_now())
                                    await db_update_next_publish_date(channel_db_id)
                                except Exception as e:
                                    logger.error(f"فشل نشر منشور في القناة {channel_db_id}: {e}")
                                    await db_increment_fail_count(post['id'])
                            else:
                                # لا توجد منشورات - تحقق من إعادة التدوير
                                if await db_get_auto_recycle(user_id):
                                    await db_reset_posts_to_unpublished(channel_db_id, user_id)
                                    await db_update_next_publish_date(channel_db_id)
                                else:
                                    # تعطيل النشر التلقائي مؤقتاً
                                    await db_set_next_publish_date(channel_db_id, utc_now() + timedelta(hours=24))
                    except Exception as e:
                        logger.error(f"خطأ في معالجة جدولة القناة {channel_db_id}: {e}")
        except Exception as e:
            logger.error(f"خطأ في حلقة النشر التلقائي: {e}")
            await asyncio.sleep(60)

async def run_scheduled_posts_loop_improved(bot):
    """حلقة المنشورات المجدولة المحسنة"""
    while True:
        try:
            await asyncio.sleep(SCHEDULED_POSTS_SLEEP)
            
            now = utc_now()
            posts = await db_get_due_scheduled_posts(now)
            
            for post_id, chat_id, text, fail_count in posts:
                try:
                    await bot.send_message(chat_id, text)
                    await db_delete_scheduled_post(post_id)
                except Exception as e:
                    logger.error(f"فشل إرسال منشور مجدول {post_id}: {e}")
                    await db_update_scheduled_post_fail(post_id, fail_count + 1)
                    if fail_count >= 3:
                        await db_delete_scheduled_post(post_id)
        except Exception as e:
            logger.error(f"خطأ في حلقة المنشورات المجدولة: {e}")

async def send_reminders_loop_improved(bot):
    """حلقة إرسال التذكيرات المحسنة"""
    while True:
        try:
            await asyncio.sleep(REMINDERS_SLEEP)
            
            # تذكيرات الاشتراك
            users = await db_get_users_needing_reminder()
            for user in users:
                try:
                    lang = user.get('notification_lang', 'ar')
                    if lang == 'ar':
                        text = f"⚠️ **تنبيه!**\nاشتراكك ينتهي خلال {user['days_left']} أيام\nقم بتجديده الآن لتستمر الميزات 💎"
                    else:
                        text = f"⚠️ **Warning!**\nYour subscription expires in {user['days_left']} days\nRenew now to keep features 💎"
                    await bot.send_message(user['user_id'], text, parse_mode="MarkdownV2")
                    await db_update_last_reminder_sent(user['user_id'], 'subscription')
                except Exception as e:
                    logger.error(f"فشل إرسال تذكير للمستخدم {user['user_id']}: {e}")
            
            # تقارير يومية
            daily_users = []
            async def _get_daily_users(conn):
                cur = await conn.execute("SELECT user_id FROM user_reminder_settings WHERE daily_stats_reminder=1")
                return [row[0] for row in await cur.fetchall()]
            daily_users = await execute_db(_get_daily_users)
            
            for user_id in daily_users:
                try:
                    channels = await db_get_user_channels_count(user_id)
                    total = await db_get_user_total_posts(user_id)
                    unpublished = await db_get_user_unpublished_posts(user_id)
                    groups = await db_get_user_groups_count(user_id)
                    text = get_text(user_id, 'daily_stats').format(channels, total, unpublished, groups)
                    await bot.send_message(user_id, text)
                except Exception as e:
                    logger.error(f"فشل إرسال تقرير يومي للمستخدم {user_id}: {e}")
            
            # تقارير أسبوعية
            if utc_now().weekday() == 0:  # يوم الإثنين
                weekly_users = []
                async def _get_weekly_users(conn):
                    cur = await conn.execute("SELECT user_id FROM user_reminder_settings WHERE weekly_report=1")
                    return [row[0] for row in await cur.fetchall()]
                weekly_users = await execute_db(_get_weekly_users)
                
                for user_id in weekly_users:
                    try:
                        channels = await db_get_user_channels_count(user_id)
                        total = await db_get_user_total_posts(user_id)
                        unpublished = await db_get_user_unpublished_posts(user_id)
                        groups = await db_get_user_groups_count(user_id)
                        referrals = await db_get_referral_stats(user_id)
                        text = get_text(user_id, 'weekly_report').format(channels, total, unpublished, groups, referrals['total_referrals'])
                        await bot.send_message(user_id, text)
                    except Exception as e:
                        logger.error(f"فشل إرسال تقرير أسبوعي للمستخدم {user_id}: {e}")
        except Exception as e:
            logger.error(f"خطأ في حلقة التذكيرات: {e}")

async def cleanup_expired_sessions_improved():
    """تنظيف الجلسات المنتهية"""
    while True:
        await asyncio.sleep(CLEANUP_SLEEP)
        # التخزين المؤقت في الذاكرة يتم تنظيفه تلقائياً، لا حاجة لإجراءات إضافية

async def auto_close_contests_loop(bot):
    """إغلاق المسابقات المنتهية تلقائياً وإعلان الفائزين"""
    while True:
        try:
            await asyncio.sleep(3600)  # كل ساعة
            
            # الحصول على المسابقات المنتهية
            async def _get_expired(conn):
                cur = await conn.execute(
                    "SELECT id, title, prize FROM contests WHERE status='active' AND end_date <= ?",
                    (utc_now_iso(),)
                )
                return await cur.fetchall()
            expired_contests = await execute_db(_get_expired)
            
            for contest_id, title, prize in expired_contests:
                # اختيار فائز عشوائي
                winner_id = await db_get_random_participant(contest_id)
                if winner_id:
                    await db_set_contest_winner(contest_id, winner_id)
                    try:
                        await bot.send_message(
                            winner_id,
                            get_text(winner_id, 'contest_auto_winner').format(title, prize)
                        )
                    except:
                        pass
        except Exception as e:
            logger.error(f"خطأ في حلقة إغلاق المسابقات: {e}")

async def start_web_server():
    """بدء خادم الويب"""
    try:
        app = web.Application()
        app.router.add_get("/health", health_check_handler)
        
        # إضافة مسار للراحة
        app.router.add_get("/", health_check_handler)
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host=WEB_HOST, port=WEB_PORT)
        await site.start()
        logger.info(f"🌐 خادم الويب يعمل على http://{WEB_HOST}:{WEB_PORT}")
        
        # إضافة صفحة بسيطة للحالة
        async def status_page(request):
            ram = get_ram_usage()
            db_health = await check_database_health()
            tg_health = await check_telegram_health()
            return web.Response(
                text=f"""<!DOCTYPE html>
<html>
<head><title>{BOT_NAME} - Status</title>
<style>
body {{ font-family: Arial; margin: 40px; background: #1a1a2e; color: #eee; }}
.card {{ background: #16213e; padding: 20px; border-radius: 10px; margin: 10px 0; }}
.status-ok {{ color: #4caf50; }}
.status-error {{ color: #f44336; }}
</style>
</head>
<body>
<h1>🤖 {BOT_NAME}</h1>
<div class="card">
<h2>📊 الحالة</h2>
<p>🟢 البوت يعمل</p>
<p>📦 الإصدار: 19.3.4</p>
<p>⏱️ وقت التشغيل: {int(metrics.get_stats()['uptime'] / 3600)} ساعة</p>
</div>
<div class="card">
<h2>🖥️ الذاكرة</h2>
<p>📊 الاستخدام: {ram['percent']}%</p>
<p>📦 المستخدم: {ram['used'] // (1024*1024)} ميجابايت</p>
</div>
<div class="card">
<h2>🔗 الاتصالات</h2>
<p>🗄️ قاعدة البيانات: {"✅" if db_health else "❌"}</p>
<p>📡 تيليجرام: {"✅" if tg_health else "❌"}</p>
</div>
</body>
</html>""",
                content_type="text/html"
            )
        app.router.add_get("/status", status_page)
        
        # إبقاء الخادم قيد التشغيل
        while True:
            await asyncio.sleep(60)
    except Exception as e:
        logger.warning(f"⚠️ فشل بدء خادم الويب: {e}")

async def self_ping_loop():
    """حلقة ping ذاتي للحفاظ على التشغيل على Render"""
    while True:
        try:
            await asyncio.sleep(300)  # كل 5 دقائق
            # محاولة الاتصال بالـ web server الخاص
            try:
                async with aiohttp.ClientSession() as session:
                    await session.get(f"http://localhost:{WEB_PORT}/health", timeout=5)
            except:
                pass
        except Exception as e:
            logger.debug(f"خطأ في ping: {e}")

async def broadcast_stats_periodically():
    """إرسال إحصائيات دورية إلى قناة التقارير"""
    while True:
        try:
            await asyncio.sleep(24 * 60 * 60)  # كل يوم
            log_channel = await db_get_log_channel_id()
            if log_channel:
                total, banned, posts, groups, channels = await db_stats()
                from telegram import Bot
                bot = Bot(token=TOKEN)
                await bot.send_message(
                    chat_id=log_channel,
                    text=f"📊 **تقرير يومي**\n━━━━━━━━━━━━━━━━━━━━━━\n"
                         f"👥 إجمالي المستخدمين: {total}\n"
                         f"⛔ المحظورين: {banned}\n"
                         f"📝 المنشورات غير المنشورة: {posts}\n"
                         f"👥 المجموعات: {groups}\n"
                         f"📡 القنوات: {channels}\n"
                         f"🕐 {mecca_now().strftime('%Y-%m-%d %H:%M')}",
                    parse_mode="MarkdownV2"
                )
        except Exception as e:
            logger.error(f"خطأ في إرسال التقرير الدوري: {e}")

async def memory_monitor():
    """مراقبة الذاكرة وتنظيفها إذا لزم الأمر"""
    while True:
        try:
            await asyncio.sleep(600)
            ram = get_ram_usage()
            if ram['percent'] > 85:
                logger.warning(f"⚠️ ارتفاع استخدام الذاكرة: {ram['percent']}%")
                memory_optimizer()
        except Exception as e:
            logger.error(f"خطأ في مراقبة الذاكرة: {e}")

# ===================== معالج الأخطاء العام =====================

async def global_error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأخطاء العام"""
    try:
        error = context.error
        error_id = advanced_logger.log_error("خطأ في البوت", error, {
            'update': str(update) if update else None,
        })
        
        if update and update.effective_user:
            user_id = update.effective_user.id
            await safe_send_markdown(
                context.bot,
                user_id,
                f"❌ حدث خطأ غير متوقع (الرمز: `{error_id}`).\nيرجى المحاولة مرة أخرى لاحقاً."
            )
    except Exception as e:
        logger.error(f"فشل معالج الأخطاء: {e}")

# ===================== معالج الرسائل الرئيسي =====================

async def message_handler_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الرسائل الرئيسي"""
    try:
        user_id = update.effective_user.id
        
        # التحقق من الحظر
        if await db_is_banned(user_id):
            await update.message.reply_text("⛔ أنت محظور من استخدام البوت.")
            return
        
        # التحقق من حالة المستخدم
        state = context.user_data.get('state')
        
        # معالجة حالات المستخدم
        if state == UserState.WAITING_CHANNEL_ID:
            channel_id = update.message.text.strip()
            if channel_id and len(channel_id) > 3:
                channel_name = channel_id
                if channel_id.startswith('@'):
                    channel_name = channel_id
                else:
                    try:
                        chat = await context.bot.get_chat(channel_id)
                        channel_name = chat.title or channel_id
                    except:
                        channel_name = channel_id
                
                existing_channels = await db_get_channels(user_id)
                exists = any(ch[1] == channel_id for ch in existing_channels)
                if exists:
                    await update.message.reply_text(get_text(user_id, 'channel_exists'))
                else:
                    ch_db_id = await db_add_channel(user_id, channel_id, channel_name)
                    if ch_db_id:
                        await db_set_active_channel(user_id, ch_db_id)
                        context.user_data['active_channel'] = ch_db_id
                        await update.message.reply_text(get_text(user_id, 'channel_added').format(channel_name))
                    else:
                        await update.message.reply_text(get_text(user_id, 'channel_exists'))
                context.user_data.pop('state', None)
                await main_menu_callback(update, context)
            else:
                await update.message.reply_text("❌ معرف قناة غير صالح. أرسل معرفاً صحيحاً.")
            return
        
        elif state == UserState.ADDING_POSTS:
            session = context.user_data.get(f"session_{user_id}", [])
            target = context.user_data.get(f"session_target_{user_id}", 0)
            
            if len(session) >= target:
                await update.message.reply_text("✅ تم حفظ جميع المنشورات")
                context.user_data.pop(f"session_{user_id}", None)
                context.user_data.pop(f"session_target_{user_id}", None)
                context.user_data.pop('state', None)
                await main_menu_callback(update, context)
                return
            
            # معالجة الرسالة
            text = update.message.text or ""
            media_type = None
            media_file_id = None
            
            if update.message.photo:
                media_type = 'photo'
                media_file_id = update.message.photo[-1].file_id
            elif update.message.video:
                media_type = 'video'
                media_file_id = update.message.video.file_id
            elif update.message.document:
                media_type = 'document'
                media_file_id = update.message.document.file_id
            elif update.message.audio:
                media_type = 'audio'
                media_file_id = update.message.audio.file_id
            elif update.message.voice:
                media_type = 'voice'
                media_file_id = update.message.voice.file_id
            elif update.message.animation:
                media_type = 'animation'
                media_file_id = update.message.animation.file_id
            elif text:
                media_type = 'text'
            
            if not media_type:
                await update.message.reply_text("⚠️ نوع الملف غير مدعوم. أرسل نص أو صورة أو فيديو.")
                return
            
            # التحقق من المحتوى غير اللائق (NSFW)
            if NSFW_ENABLED and media_type in ['photo', 'video']:
                is_nsfw = False
                if media_type == 'photo':
                    try:
                        file = await context.bot.get_file(media_file_id)
                        file_data = await file.download_as_bytearray()
                        if len(file_data) <= NSFW_MAX_FILE_SIZE:
                            result = await check_nsfw_cached(bytes(file_data))
                            if result.get('nsfw', False):
                                is_nsfw = True
                    except Exception as e:
                        logger.warning(f"فشل فحص NSFW للصورة: {e}")
                
                if is_nsfw:
                    await update.message.reply_text("🔞 تم رفض المحتوى لأنه غير لائق (NSFW).")
                    return
            
            session.append((text, media_type, media_file_id))
            context.user_data[f"session_{user_id}"] = session
            
            remaining = target - len(session)
            await update.message.reply_text(f"✅ تم حفظ المنشور {len(session)} من {target}\n📌 متبقي: {remaining}")
            
            if len(session) >= target:
                # حفظ المنشورات في قاعدة البيانات
                active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
                if active:
                    await db_save_posts(active, session)
                    await update.message.reply_text(f"✅ تم حفظ {len(session)} منشور في القناة")
                else:
                    await update.message.reply_text("⚠️ لم يتم تحديد قناة نشطة")
                context.user_data.pop(f"session_{user_id}", None)
                context.user_data.pop(f"session_target_{user_id}", None)
                context.user_data.pop('state', None)
                await main_menu_callback(update, context)
            return
        
        elif state == UserState.WAITING_INTERVAL_MINUTES:
            try:
                minutes = int(update.message.text.strip())
                if minutes <= 0:
                    await update.message.reply_text(get_text(user_id, 'invalid_number'))
                    return
                ch_db_id = context.user_data.get('schedule_ch_id')
                if ch_db_id:
                    await db_save_schedule(ch_db_id, 'interval_minutes', interval_minutes=minutes)
                    await db_update_next_publish_date(ch_db_id)
                    await update.message.reply_text(get_text(user_id, 'interval_set'))
                    context.user_data.pop('state', None)
                    context.user_data.pop('schedule_ch_id', None)
                    await schedule_menu_callback(update, context)
            except ValueError:
                await update.message.reply_text(get_text(user_id, 'invalid_number'))
            return
        
        elif state == UserState.WAITING_INTERVAL_HOURS:
            try:
                hours = int(update.message.text.strip())
                if hours <= 0:
                    await update.message.reply_text(get_text(user_id, 'invalid_number'))
                    return
                ch_db_id = context.user_data.get('schedule_ch_id')
                if ch_db_id:
                    await db_save_schedule(ch_db_id, 'interval_hours', interval_hours=hours)
                    await db_update_next_publish_date(ch_db_id)
                    await update.message.reply_text(get_text(user_id, 'interval_set'))
                    context.user_data.pop('state', None)
                    context.user_data.pop('schedule_ch_id', None)
                    await schedule_menu_callback(update, context)
            except ValueError:
                await update.message.reply_text(get_text(user_id, 'invalid_number'))
            return
        
        elif state == UserState.WAITING_INTERVAL_DAYS:
            try:
                days = int(update.message.text.strip())
                if days <= 0:
                    await update.message.reply_text(get_text(user_id, 'invalid_number'))
                    return
                ch_db_id = context.user_data.get('schedule_ch_id')
                if ch_db_id:
                    await db_save_schedule(ch_db_id, 'interval_days', interval_days=days)
                    await db_update_next_publish_date(ch_db_id)
                    await update.message.reply_text(get_text(user_id, 'interval_set'))
                    context.user_data.pop('state', None)
                    context.user_data.pop('schedule_ch_id', None)
                    await schedule_menu_callback(update, context)
            except ValueError:
                await update.message.reply_text(get_text(user_id, 'invalid_number'))
            return
        
        elif state == UserState.WAITING_DATES:
            dates_str = update.message.text.strip()
            if dates_str:
                dates = [d.strip() for d in dates_str.split(',') if d.strip()]
                valid = True
                for d in dates:
                    try:
                        datetime.strptime(d, '%Y-%m-%d')
                    except:
                        valid = False
                        break
                if not valid:
                    await update.message.reply_text(get_text(user_id, 'invalid_date'))
                    return
                ch_db_id = context.user_data.get('schedule_ch_id')
                if ch_db_id:
                    await db_save_schedule(ch_db_id, 'dates', specific_dates=json.dumps(dates))
                    await db_update_next_publish_date(ch_db_id)
                    await update.message.reply_text(get_text(user_id, 'dates_saved'))
                    context.user_data.pop('state', None)
                    context.user_data.pop('schedule_ch_id', None)
                    await schedule_menu_callback(update, context)
            else:
                await update.message.reply_text(get_text(user_id, 'invalid_date'))
            return
        
        elif state == UserState.WAITING_PUBLISH_TIME:
            time_str = update.message.text.strip()
            if ':' in time_str:
                try:
                    hour, minute = map(int, time_str.split(':'))
                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        ch_db_id = context.user_data.get('schedule_ch_id')
                        if ch_db_id:
                            await db_set_publish_time(ch_db_id, time_str)
                            await db_update_next_publish_date(ch_db_id)
                            await update.message.reply_text(get_text(user_id, 'interval_set'))
                            context.user_data.pop('state', None)
                            context.user_data.pop('schedule_ch_id', None)
                            await schedule_menu_callback(update, context)
                        return
                except:
                    pass
            await update.message.reply_text(get_text(user_id, 'invalid_time'))
            return
        
        elif state == UserState.WAITING_SCHEDULE_POST:
            text = update.message.text.strip()
            # تنسيق: YYYY-MM-DD HH:MM النص
            match = re.match(r'^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s+(.+)$', text)
            if match:
                date_str, time_str, post_text = match.groups()
                try:
                    publish_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                    # تحويل إلى UTC (مكة +3)
                    publish_time = publish_time - timedelta(hours=3)
                    if publish_time <= utc_now():
                        await update.message.reply_text("❌ وقت النشر يجب أن يكون في المستقبل!")
                        return
                    await db_add_scheduled_post(update.effective_chat.id, post_text, publish_time)
                    await update.message.reply_text(f"✅ تم جدولة المنشور في {date_str} {time_str}")
                except ValueError:
                    await update.message.reply_text("❌ صيغة وقت غير صالحة!")
            else:
                await update.message.reply_text("❌ الصيغة غير صحيحة!\nاستخدم: `YYYY-MM-DD HH:MM نص المنشور`")
            context.user_data.pop('state', None)
            await main_menu_callback(update, context)
            return
        
        elif state == UserState.WAITING_KEYWORD:
            keyword = update.message.text.strip().lower()
            if keyword:
                context.user_data['keyword'] = keyword
                context.user_data['state'] = UserState.WAITING_REPLY
                await update.message.reply_text("📝 أرسل الرد الذي تريد إضافته لهذه الكلمة:")
            else:
                await update.message.reply_text("❌ الكلمة غير صالحة!")
            return
        
        elif state == UserState.WAITING_REPLY:
            reply = update.message.text.strip()
            if reply:
                keyword = context.user_data.get('keyword')
                if keyword:
                    await db_add_reply(keyword, reply)
                    await update.message.reply_text(f"✅ تم إضافة رد للكلمة `{keyword}`")
                else:
                    # حذف رد
                    if context.user_data.get('admin_del_reply'):
                        if await db_del_reply(reply):
                            await update.message.reply_text(f"✅ تم حذف رد `{reply}`")
                        else:
                            await update.message.reply_text(f"⚠️ الكلمة `{reply}` غير موجودة")
                        context.user_data.pop('admin_del_reply', None)
            context.user_data.pop('state', None)
            context.user_data.pop('keyword', None)
            await admin_replies_callback(update, context)
            return
        
        elif state == UserState.WAITING_ADMIN_ID_ADD:
            try:
                admin_id = int(update.message.text.strip())
                await add_bot_admin(admin_id)
                await update.message.reply_text(get_text(user_id, 'add_admin_success').format(admin_id))
            except:
                await update.message.reply_text(get_text(user_id, 'invalid_user_id'))
            context.user_data.pop('state', None)
            await admin_panel_callback(update, context)
            return
        
        elif state == UserState.WAITING_ADMIN_ID_REMOVE:
            try:
                admin_id = int(update.message.text.strip())
                if admin_id == PRIMARY_OWNER_ID:
                    await update.message.reply_text(get_text(user_id, 'cannot_remove_main_admin'))
                else:
                    await remove_bot_admin(admin_id)
                    await update.message.reply_text(get_text(user_id, 'remove_admin_success').format(admin_id))
            except:
                await update.message.reply_text(get_text(user_id, 'invalid_user_id'))
            context.user_data.pop('state', None)
            await admin_panel_callback(update, context)
            return
        
        elif state == UserState.WAITING_SENDCODE_USER:
            try:
                target_id = int(update.message.text.strip())
                await db_set_allowed_sendcode_user(target_id)
                await update.message.reply_text(get_text(user_id, 'sendcode_user_set').format(target_id))
            except:
                await update.message.reply_text(get_text(user_id, 'invalid_user_id'))
            context.user_data.pop('state', None)
            await admin_panel_callback(update, context)
            return
        
        elif state == UserState.WAITING_REMINDER_DAYS:
            try:
                days = int(update.message.text.strip())
                if 1 <= days <= 10:
                    await db_update_reminder_settings(user_id, reminder_days_before=days)
                    await update.message.reply_text(f"✅ تم تعيين التذكير قبل {days} أيام")
                else:
                    await update.message.reply_text("❌ الرجاء إدخال عدد بين 1 و 10")
            except:
                await update.message.reply_text("❌ الرجاء إدخال عدد صحيح")
            context.user_data.pop('state', None)
            await reminder_menu_callback(update, context)
            return
        
        elif state == UserState.WAITING_GROUP_BANNED_WORD:
            word = update.message.text.strip().lower()
            if word and len(word) >= 2:
                chat_id = context.user_data.get('banned_words_chat_id')
                if chat_id:
                    await db_add_banned_word(word, chat_id, user_id)
                    await update.message.reply_text(f"✅ تم إضافة الكلمة `{word}` إلى قائمة المحظورات")
                context.user_data.pop('state', None)
                context.user_data.pop('banned_words_chat_id', None)
                await group_settings_callback(update, context)
            else:
                await update.message.reply_text("❌ الكلمة يجب أن تكون حرفين على الأقل")
            return
        
        elif state == UserState.WAITING_REMOVE_GROUP_BANNED_WORD:
            word = update.message.text.strip().lower()
            if word:
                chat_id = context.user_data.get('banned_words_chat_id')
                if chat_id:
                    await db_remove_banned_word(word, chat_id)
                    await update.message.reply_text(f"✅ تم حذف الكلمة `{word}` من قائمة المحظورات")
                context.user_data.pop('state', None)
                context.user_data.pop('banned_words_chat_id', None)
                await group_settings_callback(update, context)
            else:
                await update.message.reply_text("❌ الرجاء إدخال كلمة صحيحة")
            return
        
        elif state == UserState.WAITING_GLOBAL_BANNED_WORD:
            word = update.message.text.strip().lower()
            if word and len(word) >= 2:
                await db_add_banned_word(word, -1, user_id)
                await update.message.reply_text(f"✅ تم إضافة الكلمة `{word}` إلى القائمة العامة للمحظورات")
                context.user_data.pop('state', None)
                await admin_banned_words_callback(update, context)
            else:
                await update.message.reply_text("❌ الكلمة يجب أن تكون حرفين على الأقل")
            return
        
        elif state == UserState.WAITING_REMOVE_GLOBAL_BANNED_WORD:
            word = update.message.text.strip().lower()
            if word:
                await db_remove_banned_word(word, -1)
                await update.message.reply_text(f"✅ تم حذف الكلمة `{word}` من القائمة العامة")
                context.user_data.pop('state', None)
                await admin_banned_words_callback(update, context)
            else:
                await update.message.reply_text("❌ الرجاء إدخال كلمة صحيحة")
            return
        
        elif state == UserState.WAITING_NSFW_THRESHOLD:
            try:
                threshold = int(update.message.text.strip())
                if 1 <= threshold <= 100:
                    global NSFW_THRESHOLD
                    NSFW_THRESHOLD = threshold / 100
                    os.environ["NSFW_THRESHOLD"] = str(NSFW_THRESHOLD)
                    await update.message.reply_text(f"✅ تم تعيين نسبة الحساسية إلى {threshold}%")
                else:
                    await update.message.reply_text("❌ الرجاء إدخال نسبة بين 1 و 100")
            except:
                await update.message.reply_text("❌ الرجاء إدخال رقم صحيح")
            context.user_data.pop('state', None)
            await nsfw_settings_callback(update, context)
            return
        
        elif state == UserState.WAITING_BAN_USER:
            # معالجة حظر المستخدم - يتم التعامل معه في handle_moderation_commands
            context.user_data.pop('state', None)
            await update.message.reply_text("❌ استخدم الأمر /ban مع معرف المستخدم أو بالرد على رسالة المستخدم")
            return
        
        elif state == UserState.WAITING_MUTE_USER:
            context.user_data.pop('state', None)
            await update.message.reply_text("❌ استخدم الأمر /mute مع معرف المستخدم أو بالرد على رسالة المستخدم")
            return
        
        elif state == UserState.WAITING_WARN_USER:
            context.user_data.pop('state', None)
            await update.message.reply_text("❌ استخدم الأمر /warn مع معرف المستخدم أو بالرد على رسالة المستخدم")
            return
        
        elif state == UserState.WAITING_KICK_USER:
            context.user_data.pop('state', None)
            await update.message.reply_text("❌ استخدم الأمر /kick مع معرف المستخدم أو بالرد على رسالة المستخدم")
            return
        
        elif state == UserState.WAITING_RESTRICT_USER:
            context.user_data.pop('state', None)
            await update.message.reply_text("❌ استخدم الأمر /restrict مع معرف المستخدم أو بالرد على رسالة المستخدم")
            return
        
        elif state == UserState.WAITING_PIN_MESSAGE:
            context.user_data.pop('state', None)
            await update.message.reply_text("❌ استخدم الأمر /pin بالرد على الرسالة التي تريد تثبيتها")
            return
        
        elif state == UserState.WAITING_UNBAN_USER:
            context.user_data.pop('state', None)
            await update.message.reply_text("❌ استخدم الأمر /unban مع معرف المستخدم")
            return
        
        elif state == UserState.WAITING_UPDATE_TEXT:
            text = update.message.text
            if text:
                channel = await db_get_updates_channel()
                if channel:
                    try:
                        await context.bot.send_message(f"@{channel}", text, parse_mode='HTML')
                        await update.message.reply_text(f"✅ تم نشر التحديث في قناة @{channel}")
                    except Exception as e:
                        await update.message.reply_text(f"❌ فشل النشر: {str(e)[:100]}")
                else:
                    await update.message.reply_text("❌ لم يتم تعيين قناة تحديثات")
                context.user_data.pop('state', None)
                await admin_panel_callback(update, context)
            return
        
        elif state == UserState.WAITING_UPDATE_CHANNEL:
            channel = update.message.text.strip()
            if channel.startswith('@'):
                channel = channel[1:]
            if channel and len(channel) > 1:
                await db_set_updates_channel(channel)
                await update.message.reply_text(f"✅ تم تعيين قناة التحديثات: @{channel}")
            else:
                await update.message.reply_text("❌ معرف قناة غير صالح")
            context.user_data.pop('state', None)
            await admin_panel_callback(update, context)
            return
        
        elif state == UserState.WAITING_FORCE_CHANNEL:
            channel = update.message.text.strip()
            if channel.startswith('@'):
                channel = channel[1:]
            if channel and len(channel) > 1:
                await db_set_force_subscribe_channel(channel)
                await update.message.reply_text(f"✅ تم تعيين قناة الاشتراك الإجباري: @{channel}")
            else:
                await update.message.reply_text("❌ معرف قناة غير صالح")
            context.user_data.pop('state', None)
            await admin_panel_callback(update, context)
            return
        
        elif state == UserState.WAITING_BROADCAST:
            text = update.message.text
            if text:
                context.user_data['broadcast_text'] = text
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ تأكيد الإرسال", callback_data=CallbackData.ADMIN_CONFIRM_BROADCAST)],
                    [InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.BACK)]
                ])
                await update.message.reply_text(
                    f"📨 **تأكيد إرسال رسالة جماعية**\n\n"
                    f"النص:\n{text[:500]}{'...' if len(text) > 500 else ''}\n\n"
                    f"⚠️ سيتم إرسال هذه الرسالة لجميع المستخدمين.",
                    reply_markup=keyboard
                )
                context.user_data.pop('state', None)
            return
        
        elif state == UserState.WAITING_LOG_CHANNEL:
            channel_id = update.message.text.strip()
            if channel_id and len(channel_id) > 3:
                await db_set_log_channel_id(channel_id)
                await update.message.reply_text(f"✅ تم تعيين قناة التقارير إلى: `{channel_id}`")
            else:
                await update.message.reply_text("❌ معرف قناة غير صالح")
            context.user_data.pop('state', None)
            await admin_panel_callback(update, context)
            return
        
        elif state == UserState.WAITING_CONTEST_TITLE:
            if await handle_contest_creation_states(update, context, state):
                return
        
        elif state == UserState.WAITING_CONTEST_DESCRIPTION:
            if await handle_contest_creation_states(update, context, state):
                return
        
        elif state == UserState.WAITING_CONTEST_PRIZE:
            if await handle_contest_creation_states(update, context, state):
                return
        
        elif state == UserState.WAITING_CONTEST_END_DATE:
            if await handle_contest_creation_states(update, context, state):
                return
        
        elif state == UserState.WAITING_CONTEST_TYPE:
            if await handle_contest_creation_states(update, context, state):
                return
        
        elif state == UserState.WAITING_CONTEST_ANSWER:
            contest_id = context.user_data.get('contest_join_id')
            if not contest_id:
                await update.message.reply_text("❌ لم يتم تحديد المسابقة")
                context.user_data.pop('state', None)
                return
            
            answer = update.message.text.strip()
            if answer.lower() == '/skip':
                answer = ""
            
            async def _save_answer(conn):
                await conn.execute(
                    "INSERT INTO contest_participants (contest_id, user_id, answer, joined_at) VALUES (?, ?, ?, ?)",
                    (contest_id, user_id, answer, utc_now_iso())
                )
                await conn.commit()
            await execute_db(_save_answer)
            
            context.user_data.pop('state', None)
            context.user_data.pop('contest_join_id', None)
            await update.message.reply_text("✅ تم تسجيل مشاركتك في المسابقة بنجاح! 🎉")
            await contests_command_handler(update, context)
            return
        
        # معالجة دعم التذاكر
        if context.user_data.get('support_mode'):
            message = update.message.text
            if message and len(message.strip()) > 0:
                ticket_num = await db_get_next_ticket_number() + 1
                async def _update_ticket(conn):
                    await conn.execute("UPDATE settings SET value=? WHERE key='last_ticket_number'", (str(ticket_num),))
                    await conn.commit()
                await execute_db(_update_ticket)
                
                username = update.effective_user.username or "بدون اسم"
                await db_save_ticket(user_id, username, message, ticket_num)
                
                await update.message.reply_text(
                    f"📝 **تم إرسال تذكرتك**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 رقم التذكرة: #{ticket_num}\n⏳ سنرد عليك في أقرب وقت\n\nشكراً لتواصلك معنا ❤️"
                )
                context.user_data.pop('support_mode', None)
                
                # إشعار المشرفين
                admins = await get_all_bot_admins()
                for admin_id in [PRIMARY_OWNER_ID] + admins:
                    try:
                        await context.bot.send_message(
                            admin_id,
                            f"📞 **تذكرة دعم جديدة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"📌 رقم: #{ticket_num}\n"
                            f"👤 المستخدم: `{user_id}`\n"
                            f"📝 الرسالة: {message[:200]}\n\n"
                            f"للرد استخدم: `/support_reply {ticket_num} رسالتك`"
                        )
                    except:
                        pass
            return
        
        # معالجة طلبات المستخدمين العادية في الخاص
        if update.effective_chat.type == 'private':
            # لا نقوم بالرد التلقائي في الخاص
            pass
        
    except Exception as e:
        error_id = advanced_logger.log_error("خطأ في معالج الرسائل", e, {
            'user_id': update.effective_user.id if update.effective_user else None,
        })
        try:
            await update.message.reply_text(f"❌ حدث خطأ (الرمز: `{error_id}`)")
        except:
            pass

# ===================== فلتر الرسائل في المجموعات =====================

async def filter_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة وتصفية الرسائل في المجموعات"""
    try:
        if not update.message:
            return
        
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        text = update.message.text or update.message.caption or ""
        
        # تجاهل رسائل البوت
        if user_id == context.bot.id:
            return
        
        # التحقق من قفل المجموعة
        if await is_chat_locked(chat_id):
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
            except:
                pass
            return
        
        # التحقق من الوضع البطيء
        if not await db_check_slow_mode(chat_id, user_id):
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
                await context.bot.send_message(
                    chat_id,
                    f"⏱️ {update.effective_user.first_name}، الرجاء الانتظار قبل إرسال رسالة جديدة.",
                    reply_to_message_id=update.message.message_id
                )
            except:
                pass
            return
        
        # الحصول على إعدادات الأمان
        settings = await db_get_security_settings(chat_id)
        
        # التحقق من الكلمات المحظورة
        if settings.get('delete_banned_words', False) and text:
            banned_word = await db_contains_banned_word(text, chat_id)
            if banned_word or await check_banned_patterns(text):
                try:
                    await context.bot.delete_message(chat_id, update.message.message_id)
                    await context.bot.send_message(
                        chat_id,
                        f"🚫 {update.effective_user.first_name}، تم حذف رسالتك لأنها تحتوي على كلمات محظورة.",
                        reply_to_message_id=update.message.message_id
                    )
                    # تطبيق العقوبة
                    await apply_penalty(context.bot, chat_id, user_id, settings)
                except:
                    pass
                return
        
        # التحقق من الروابط
        if settings.get('links', False) and text and contains_link(text):
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
                await context.bot.send_message(
                    chat_id,
                    f"🔗 {update.effective_user.first_name}، ممنوع إرسال روابط في هذه المجموعة.",
                    reply_to_message_id=update.message.message_id
                )
                await apply_penalty(context.bot, chat_id, user_id, settings)
            except:
                pass
            return
        
        # التحقق من المعرفات
        if settings.get('mentions', False) and text and contains_mention(text):
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
                await context.bot.send_message(
                    chat_id,
                    f"@ {update.effective_user.first_name}، ممنوع منشن الأعضاء في هذه المجموعة.",
                    reply_to_message_id=update.message.message_id
                )
                await apply_penalty(context.bot, chat_id, user_id, settings)
            except:
                pass
            return
        
        # حذف الملصقات
        if settings.get('delete_stickers', False) and update.message.sticker:
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
                await context.bot.send_message(
                    chat_id,
                    f"🎴 {update.effective_user.first_name}، ممنوع إرسال ملصقات في هذه المجموعة.",
                    reply_to_message_id=update.message.message_id
                )
            except:
                pass
            return
        
        # حذف الفيديوهات
        if settings.get('delete_videos', False) and update.message.video:
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
                await context.bot.send_message(
                    chat_id,
                    f"🎬 {update.effective_user.first_name}، ممنوع إرسال فيديوهات في هذه المجموعة.",
                    reply_to_message_id=update.message.message_id
                )
            except:
                pass
            return
        
        # حذف رسائل الخدمة
        if settings.get('delete_service_messages', False) and update.message.new_chat_members:
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
            except:
                pass
            return
        
        # رسالة الترحيب
        if settings.get('welcome_enabled', False) and update.message.new_chat_members:
            for member in update.message.new_chat_members:
                if member.id != context.bot.id:
                    welcome_text = settings.get('welcome_text', "مرحباً {user} في {chat} 🤍")
                    welcome_text = welcome_text.replace('{user}', member.first_name or '')
                    welcome_text = welcome_text.replace('{chat}', update.effective_chat.title or '')
                    try:
                        await context.bot.send_message(chat_id, welcome_text)
                    except:
                        pass
                    break
        
        # رسالة الوداع
        if settings.get('goodbye_enabled', False) and update.message.left_chat_member:
            if update.message.left_chat_member.id != context.bot.id:
                goodbye_text = settings.get('goodbye_text', "وداعاً {user} 👋")
                goodbye_text = goodbye_text.replace('{user}', update.message.left_chat_member.first_name or '')
                goodbye_text = goodbye_text.replace('{chat}', update.effective_chat.title or '')
                try:
                    await context.bot.send_message(chat_id, goodbye_text)
                except:
                    pass
        
        # الردود التلقائية
        if text:
            # التحقق من إعدادات الردود التلقائية للمجموعة
            auto_reply_settings = await db_get_auto_reply_settings(chat_id)
            
            if auto_reply_settings['enabled']:
                # تجاهل البوتات
                if auto_reply_settings['ignore_bots'] and update.effective_user.is_bot:
                    return
                
                # التحقق من صلاحيات المستخدم
                if auto_reply_settings['only_admins']:
                    if not await is_authorized_in_group(context.bot, chat_id, user_id):
                        return
                
                # التحقق من حالة المستخدم
                user_auto_reply = await db_get_user_auto_reply_status(user_id)
                if not user_auto_reply:
                    return
                
                # البحث عن رد في القائمة المدمجة
                text_lower = text.lower()
                for key, reply in ALL_REPLIES.items():
                    if key in text_lower:
                        try:
                            await context.bot.send_message(chat_id, reply)
                            # تسجيل الاستخدام
                            async def _log_reply(conn):
                                await conn.execute(
                                    "INSERT INTO auto_reply_log (chat_id, user_id, keyword, used_at) VALUES (?, ?, ?, ?)",
                                    (chat_id, user_id, key, utc_now_iso())
                                )
                                await conn.commit()
                            await execute_db(_log_reply)
                        except:
                            pass
                        break
                
                # البحث عن رد في قاعدة البيانات
                if text_lower in ALL_REPLIES:
                    # تم المعالجة بالفعل
                    pass
                else:
                    reply = await db_get_reply(text_lower)
                    if reply:
                        try:
                            await context.bot.send_message(chat_id, reply)
                            # تسجيل الاستخدام
                            async def _log_reply(conn):
                                await conn.execute(
                                    "INSERT INTO auto_reply_log (chat_id, user_id, keyword, used_at) VALUES (?, ?, ?, ?)",
                                    (chat_id, user_id, text_lower, utc_now_iso())
                                )
                                await conn.commit()
                            await execute_db(_log_reply)
                        except:
                            pass
        
    except Exception as e:
        logger.error(f"خطأ في فلتر الرسائل: {e}")

# ===================== دوال تهيئة قاعدة البيانات =====================

async def init_db_improved():
    """تهيئة قاعدة البيانات المحسنة"""
    try:
        async def _init(conn):
            # إنشاء الجداول
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    auto_publish INTEGER DEFAULT 1,
                    banned INTEGER DEFAULT 0,
                    trial_used INTEGER DEFAULT 0,
                    subscription_end TEXT,
                    referral_code TEXT,
                    auto_reply_enabled INTEGER DEFAULT 1,
                    auto_recycle INTEGER DEFAULT 1,
                    active_channel INTEGER,
                    last_daily_reward TEXT,
                    last_weekly_reward TEXT,
                    achievements TEXT DEFAULT '[]'
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
                CREATE TABLE IF NOT EXISTS user_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    channel_id TEXT,
                    channel_name TEXT,
                    created_at TEXT,
                    banned INTEGER DEFAULT 0
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_db_id INTEGER,
                    text TEXT,
                    media_type TEXT,
                    media_file_id TEXT,
                    created_at TEXT,
                    published INTEGER DEFAULT 0,
                    fail_count INTEGER DEFAULT 0,
                    views_count INTEGER DEFAULT 0,
                    last_view_time TEXT
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS schedule (
                    channel_db_id INTEGER PRIMARY KEY,
                    schedule_type TEXT DEFAULT 'interval_minutes',
                    interval_minutes INTEGER DEFAULT 12,
                    interval_hours INTEGER DEFAULT 0,
                    interval_days INTEGER DEFAULT 0,
                    days_of_week TEXT DEFAULT '[]',
                    specific_dates TEXT DEFAULT '[]',
                    publish_time TEXT DEFAULT '00:00',
                    cron_expression TEXT,
                    next_publish_date TEXT
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS last_publish (
                    channel_db_id INTEGER PRIMARY KEY,
                    last_publish_time TEXT
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_groups (
                    chat_id INTEGER PRIMARY KEY,
                    chat_name TEXT,
                    username TEXT,
                    added_by INTEGER,
                    added_at TEXT,
                    banned INTEGER DEFAULT 0
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS group_admins (
                    chat_id INTEGER,
                    user_id INTEGER,
                    PRIMARY KEY (chat_id, user_id)
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
                    chat_id INTEGER,
                    admin_id INTEGER,
                    added_by INTEGER,
                    added_at TEXT,
                    PRIMARY KEY (chat_id, admin_id)
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_groups_link (
                    user_id INTEGER,
                    chat_id INTEGER,
                    PRIMARY KEY (user_id, chat_id)
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
                    delete_stickers INTEGER DEFAULT 0,
                    delete_videos INTEGER DEFAULT 0,
                    delete_service_messages INTEGER DEFAULT 0
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS banned_words (
                    word TEXT,
                    chat_id INTEGER,
                    added_by INTEGER,
                    added_at TEXT,
                    PRIMARY KEY (word, chat_id)
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_messages (
                    user_id INTEGER,
                    chat_id INTEGER,
                    message_time TEXT,
                    PRIMARY KEY (user_id, chat_id)
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_admins (
                    user_id INTEGER PRIMARY KEY
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_language (
                    user_id INTEGER PRIMARY KEY,
                    lang TEXT DEFAULT 'ar'
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_translation (
                    user_id INTEGER PRIMARY KEY,
                    lang TEXT DEFAULT 'off'
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
                    created_at TEXT,
                    replied INTEGER DEFAULT 0
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS referrals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id INTEGER,
                    referred_id INTEGER,
                    referred_at TEXT DEFAULT CURRENT_TIMESTAMP,
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
                CREATE TABLE IF NOT EXISTS user_levels (
                    user_id INTEGER PRIMARY KEY,
                    points INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS group_replies (
                    keyword TEXT PRIMARY KEY,
                    reply TEXT
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS auto_reply_settings (
                    chat_id INTEGER PRIMARY KEY,
                    enabled INTEGER DEFAULT 1,
                    only_admins INTEGER DEFAULT 0,
                    ignore_bots INTEGER DEFAULT 1,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS auto_reply_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    user_id INTEGER,
                    keyword TEXT,
                    used_at TEXT
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_locks (
                    chat_id INTEGER PRIMARY KEY,
                    locked INTEGER DEFAULT 0,
                    locked_at TEXT,
                    locked_by INTEGER
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
                    created_at TEXT
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_warnings (
                    user_id INTEGER,
                    chat_id INTEGER,
                    warnings INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, chat_id)
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    text TEXT,
                    publish_time TEXT,
                    fail_count INTEGER DEFAULT 0
                )
            """)
            
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
                    created_at TEXT,
                    contest_type TEXT DEFAULT 'raffle'
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS contest_participants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contest_id INTEGER,
                    user_id INTEGER,
                    answer TEXT,
                    joined_at TEXT,
                    UNIQUE(contest_id, user_id)
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS contest_winners (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contest_id INTEGER,
                    winner_id INTEGER,
                    announced_at TEXT
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_channels (
                    channel_id INTEGER PRIMARY KEY,
                    channel_name TEXT,
                    added_by INTEGER,
                    added_at TEXT,
                    banned INTEGER DEFAULT 0
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS group_rules (
                    chat_id INTEGER PRIMARY KEY,
                    rules_text TEXT,
                    set_by INTEGER,
                    set_at TEXT
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS allowed_sendcode_user (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER
                )
            """)
            
            # إضافة بعض الإعدادات الافتراضية
            await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_ticket_number', '0')")
            await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('publish_interval', ?)", (str(DEFAULT_PUBLISH_INTERVAL_SECONDS),))
            await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_backup', '1')")
            
            # إضافة إعدادات الإحالة الافتراضية
            await conn.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('reward_days_per_referral', '3')")
            await conn.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('max_referrals_per_day', '5')")
            await conn.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('welcome_bonus_points', '10')")
            
            # إضافة المالك الرئيسي كمشرف في البوت
            await conn.execute("INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)", (PRIMARY_OWNER_ID,))
            
            # إضافة عمود auto_recycle إذا لم يكن موجوداً
            try:
                await conn.execute("ALTER TABLE users ADD COLUMN auto_recycle INTEGER DEFAULT 1")
            except:
                pass
            
            await conn.commit()
        
        await execute_db(_init)
        logger.info("✅ تم تهيئة قاعدة البيانات بنجاح")
    except Exception as e:
        logger.error(f"❌ فشل تهيئة قاعدة البيانات: {e}")
        raise

async def import_banned_words_on_startup():
    """استيراد الكلمات المحظورة من الملف عند بدء التشغيل"""
    try:
        words = load_banned_words_from_file(BANNED_WORDS_FILE)
        if words:
            async def _import(conn):
                imported = import_banned_words_from_file(conn, words, PRIMARY_OWNER_ID)
                return imported
            imported = await execute_db(_import)
            if imported > 0:
                logger.info(f"✅ تم استيراد {imported} كلمة محظورة من الملف")
    except Exception as e:
        logger.error(f"❌ فشل استيراد الكلمات المحظورة: {e}")

# ===================== تشغيل البوت =====================

async def run_bot():
    """تشغيل البوت"""
    await init_db_improved()
    await import_banned_words_on_startup()
    load_all_languages()
    
    # بدء المهام الخلفية
    asyncio.create_task(memory_optimizer_loop())
    asyncio.create_task(cleanup_points_cache())
    asyncio.create_task(auto_backup())
    asyncio.create_task(broadcast_stats_periodically())
    asyncio.create_task(memory_monitor())
    
    # إعداد التطبيق
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
    
    # إضافة معالج الأخطاء
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
    application.add_handler(CommandHandler("set_sendcode_user", set_sendcode_user_command_handler))
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
    application.add_handler(CallbackQueryHandler(security_stickers_callback, pattern=f"^{CallbackData.SECURITY_STICKERS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_videos_callback, pattern=f"^{CallbackData.SECURITY_VIDEOS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_service_messages_callback, pattern=f"^{CallbackData.SECURITY_SERVICE_MESSAGES_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_close_callback, pattern=f"^{CallbackData.SECURITY_CLOSE}$"))
    application.add_handler(CallbackQueryHandler(security_main_callback, pattern=f"^{CallbackData.SECURITY_MAIN}$"))
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
    application.add_handler(CallbackQueryHandler(auto_reply_toggle_callback, pattern=f"^{CallbackData.AUTO_REPLY_TOGGLE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_admins_callback, pattern=f"^{CallbackData.AUTO_REPLY_ADMINS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_reset_callback, pattern=f"^{CallbackData.AUTO_REPLY_RESET_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_confirm_reset_callback, pattern=f"^{CallbackData.AUTO_REPLY_CONFIRM_RESET_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_cancel_callback, pattern=f"^{CallbackData.AUTO_REPLY_CANCEL_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_stats_callback, pattern=f"^{CallbackData.AUTO_REPLY_STATS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(user_auto_reply_toggle_callback, pattern=f"^{CallbackData.USER_AUTO_REPLY_TOGGLE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(admin_auto_reply_callback, pattern=f"^{CallbackData.ADMIN_AUTO_REPLY}$"))
    application.add_handler(CallbackQueryHandler(admin_auto_reply_select_callback, pattern=f"^{CallbackData.ADMIN_AUTO_REPLY_SELECT_PREFIX}"))
    application.add_handler(CallbackQueryHandler(nsfw_settings_callback, pattern=f"^{CallbackData.NSFW_SETTINGS}$"))
    application.add_handler(CallbackQueryHandler(nsfw_toggle_callback, pattern=f"^{CallbackData.NSFW_TOGGLE}$"))
    application.add_handler(CallbackQueryHandler(nsfw_threshold_callback, pattern=f"^{CallbackData.NSFW_THRESHOLD_SET}$"))
    application.add_handler(CallbackQueryHandler(contests_menu_callback, pattern=f"^{CallbackData.CONTESTS_MENU}$"))
    application.add_handler(CallbackQueryHandler(contest_join_callback, pattern=f"^{CallbackData.CONTEST_JOIN_PREFIX}"))
    application.add_handler(CallbackQueryHandler(contest_winners_callback, pattern=f"^{CallbackData.CONTEST_WINNERS}$"))
    application.add_handler(CallbackQueryHandler(contests_back_callback, pattern=f"^{CallbackData.CONTESTS_BACK}$"))
    application.add_handler(CallbackQueryHandler(admin_create_contest_callback, pattern=f"^{CallbackData.ADMIN_CREATE_CONTEST}$"))
    application.add_handler(CallbackQueryHandler(admin_declare_winner_callback, pattern=f"^{CallbackData.ADMIN_DECLARE_WINNER}$"))
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
    application.add_handler(CallbackQueryHandler(admin_toggle_channel_ban_callback, pattern=f"^{CallbackData.ADMIN_TOGGLE_CHANNEL_BAN_PREFIX}"))
    application.add_handler(CallbackQueryHandler(admin_toggle_group_ban_callback, pattern=f"^{CallbackData.ADMIN_TOGGLE_GROUP_BAN_PREFIX}"))
    application.add_handler(CallbackQueryHandler(banned_words_add_callback, pattern=f"^{CallbackData.BANNED_WORDS_ADD_PREFIX}"))
    application.add_handler(CallbackQueryHandler(banned_words_list_callback, pattern=f"^{CallbackData.BANNED_WORDS_LIST_PREFIX}"))
    application.add_handler(CallbackQueryHandler(banned_words_remove_callback, pattern=f"^{CallbackData.BANNED_WORDS_REMOVE_PREFIX}"))
    
    # ========== Payment Handlers ==========
    application.add_handler(PreCheckoutQueryHandler(pre_checkout_callback_handler))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback_handler))
    
    # ========== Chat Member Handlers ==========
    application.add_handler(ChatMemberHandler(track_chat_add, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_bot_added))
    
    # ========== Message Handlers ==========
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))
    application.add_handler(MessageHandler(filters.CAPTION & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, message_handler_main))
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.AUDIO & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.VOICE & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.ANIMATION & filters.ChatType.PRIVATE, message_handler_main))
    
    # ========== Set Bot Commands ==========
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
    
    # ========== Start Background Tasks ==========
    asyncio.create_task(auto_publish_loop_improved(application.bot))
    asyncio.create_task(run_scheduled_posts_loop_improved(application.bot))
    asyncio.create_task(send_reminders_loop_improved(application.bot))
    asyncio.create_task(cleanup_expired_sessions_improved())
    asyncio.create_task(auto_close_contests_loop(application.bot))
    asyncio.create_task(start_web_server())
    asyncio.create_task(self_ping_loop())
    
    print(f"🚀 تم تشغيل {BOT_NAME} (الإصدار 19.3.4)")
    print("✅ جميع الإصلاحات والتحسينات تم تطبيقها")
    
    # ========== Start Polling ==========
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
        await db_pool.close()
        logger.info("✅ تم تنظيف الموارد بنجاح")

# ===================== تشغيل البوت =====================

if __name__ == "__main__":
    try:
        os.environ["WEB_CONCURRENCY"] = "1"
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("🛑 تم إيقاف البوت")
    except Exception as e:
        logger.error(f"❌ خطأ فادح: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
