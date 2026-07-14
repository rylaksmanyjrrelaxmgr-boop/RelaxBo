#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers.py - معالجات البوت ريلاكس مانيجر
الإصدار: 19.2.7 - دعم كامل للمشرفين المخفيين + أزرار تفاعلية
المطور: @RelaxMgr
"""

import asyncio
import json
import re
import time
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions, ChatMember
from telegram.ext import ContextTypes
from telegram.error import BadRequest, Forbidden, TimedOut, NetworkError

# ===================== الثوابت =====================
PRIMARY_OWNER_ID = 0  # سيتم تعيينه من الملف الرئيسي

# ===================== الكاش =====================
_admin_cache = {}
_admin_cache_time = {}
_ADMIN_CACHE_TTL = 300  # 5 دقائق

_anonymous_admins_cache = {}
_ANON_CACHE_TTL = 300  # 5 دقائق

# ===================== دوال قاعدة البيانات =====================

async def db_is_hidden_owner(chat_id: int, user_id: int) -> bool:
    """التحقق من المالك المخفي"""
    return False  # سيتم استبدالها بالدالة الحقيقية

async def db_is_hidden_admin(chat_id: int, user_id: int) -> bool:
    """التحقق من المشرف المخفي"""
    return False  # سيتم استبدالها بالدالة الحقيقية

async def db_add_hidden_admin(chat_id: int, admin_id: int, added_by: int) -> bool:
    """إضافة مشرف مخفي"""
    return False  # سيتم استبدالها بالدالة الحقيقية

async def db_remove_hidden_admin(chat_id: int, admin_id: int) -> bool:
    """إزالة مشرف مخفي"""
    return False  # سيتم استبدالها بالدالة الحقيقية

async def db_get_hidden_admins(chat_id: int) -> List[Dict]:
    """جلب قائمة المشرفين المخفيين"""
    return []  # سيتم استبدالها بالدالة الحقيقية

async def db_register_hidden_owner_group(chat_id: int, owner_id: int):
    """تسجيل مالك مخفي - صامت"""
    pass  # سيتم استبدالها بالدالة الحقيقية

async def invalidate_user_cache(user_id: int = None, chat_id: int = None):
    """تنظيف الكاش"""
    pass  # سيتم استبدالها بالدالة الحقيقية

async def is_bot_admin(user_id: int) -> bool:
    """التحقق من مشرف البوت"""
    return False  # سيتم استبدالها بالدالة الحقيقية

# ===================== دوال الإجراءات =====================

async def execute_ban(bot, chat_id: int, user_id: int, until_date=None, reason: str = "", moderator_id: int = None):
    """تنفيذ حظر"""
    return True, "✅ تم الحظر"  # سيتم استبدالها بالدالة الحقيقية

async def execute_mute(bot, chat_id: int, user_id: int, duration_minutes: int = None, reason: str = "", moderator_id: int = None):
    """تنفيذ كتم"""
    return True, "✅ تم الكتم"  # سيتم استبدالها بالدالة الحقيقية

async def execute_warn(bot, chat_id: int, user_id: int, moderator_id: int, reason: str = "", auto_ban_limit: int = 3):
    """تنفيذ تحذير"""
    return True, "✅ تم التحذير"  # سيتم استبدالها بالدالة الحقيقية

async def execute_kick(bot, chat_id: int, user_id: int, reason: str = "", moderator_id: int = None):
    """تنفيذ طرد"""
    return True, "✅ تم الطرد"  # سيتم استبدالها بالدالة الحقيقية

async def execute_restrict(bot, chat_id: int, user_id: int, reason: str = "", moderator_id: int = None):
    """تنفيذ تقييد"""
    return True, "✅ تم التقييد"  # سيتم استبدالها بالدالة الحقيقية

async def execute_pin(bot, chat_id: int, message_id: int, disable_notification: bool = False):
    """تنفيذ تثبيت"""
    return True, "✅ تم التثبيت"  # سيتم استبدالها بالدالة الحقيقية

async def execute_unban(bot, chat_id: int, user_id: int, moderator_id: int = None):
    """تنفيذ إلغاء حظر"""
    return True, "✅ تم إلغاء الحظر"  # سيتم استبدالها بالدالة الحقيقية

async def execute_unmute(bot, chat_id: int, user_id: int, moderator_id: int = None):
    """تنفيذ إلغاء كتم"""
    return True, "✅ تم إلغاء الكتم"  # سيتم استبدالها بالدالة الحقيقية

# ===================== دوال مساعدة =====================

async def safe_send_markdown(bot, chat_id: int, text: str, reply_markup=None, **kwargs):
    """إرسال رسالة آمن"""
    try:
        return await bot.send_message(chat_id=chat_id, text=text, parse_mode=None, reply_markup=reply_markup, **kwargs)
    except Exception as e:
        print(f"⚠️ خطأ في safe_send_markdown: {e}")
        return None

def get_text(user_id: int, key: str) -> str:
    """جلب نص مترجم"""
    return key  # سيتم استبدالها بالدالة الحقيقية

async def check_bot_admin_permissions(bot, chat_id: int) -> dict:
    """التحقق من صلاحيات البوت"""
    return {'can_act': True, 'reason': ''}  # سيتم استبدالها بالدالة الحقيقية

async def db_set_chat_lock(chat_id: int, locked: bool, locked_by: int = None):
    """تعيين قفل المجموعة"""
    pass  # سيتم استبدالها بالدالة الحقيقية

async def is_chat_locked(chat_id: int) -> bool:
    """التحقق من قفل المجموعة"""
    return False  # سيتم استبدالها بالدالة الحقيقية

async def db_get_user_groups(user_id: int):
    """جلب مجموعات المستخدم"""
    return []  # سيتم استبدالها بالدالة الحقيقية

async def db_register_group(chat_id: int, chat_name: str, added_by: int, username: str = None) -> bool:
    """تسجيل مجموعة"""
    return True  # سيتم استبدالها بالدالة الحقيقية

# ===================== دوال السجلات =====================

def log_error(error: Exception, context: dict = None) -> str:
    """تسجيل الأخطاء وإرجاع معرف الخطأ"""
    error_id = secrets.token_hex(4)
    error_msg = f"[{error_id}] {str(error)}"
    if context:
        error_msg += f" - السياق: {json.dumps(context, default=str)[:200]}"
    print(f"❌ {error_msg}")
    import traceback
    traceback.print_exc()
    return error_id

# ===================== دوال التحقق من الصلاحيات =====================

async def is_telegram_admin(bot, chat_id: int, user_id: int) -> bool:
    """
    التحقق من صلاحيات تيليجرام فقط (بدون المخفيين في قاعدة البيانات).
    تستخدم للتحقق من المشرفين الحقيقيين عبر API تيليجرام.
    """
    try:
        # المطور الأساسي له صلاحية مطلقة
        if user_id == PRIMARY_OWNER_ID:
            return True
            
        # محاولة جلب معلومات العضو من تيليجرام
        member = await bot.get_chat_member(chat_id, user_id)
        
        # التحقق من حالة المشرف
        if member.status in ['creator', 'administrator']:
            return True
            
        return False
    except Forbidden:
        # البوت ليس مشرفاً أو ليس لديه صلاحية
        return False
    except Exception as e:
        print(f"⚠️ خطأ في is_telegram_admin: {e}")
        return False

async def get_anonymous_admins(bot, chat_id: int) -> List[int]:
    """
    جلب معرفات المشرفين المخفيين في المجموعة عبر API تيليجرام.
    المشرف المخفي هو الذي يظهر باسم المجموعة (sender_chat).
    """
    cache_key = f"anon_{chat_id}"
    now = time.time()
    
    # التحقق من الكاش
    if cache_key in _anonymous_admins_cache:
        cached_data, cached_time = _anonymous_admins_cache[cache_key]
        if now - cached_time < _ANON_CACHE_TTL:
            return cached_data
    
    anonymous_admins = []
    
    try:
        # جلب قائمة المشرفين من تيليجرام
        admins = await bot.get_chat_administrators(chat_id)
        
        for admin in admins:
            # نستثني البوت نفسه
            if admin.user.is_bot:
                continue
                
            # نضيف معرف المشرف إلى القائمة
            if admin.status in ['creator', 'administrator']:
                anonymous_admins.append(admin.user.id)
        
        # تخزين في الكاش
        _anonymous_admins_cache[cache_key] = (anonymous_admins, now)
        
        # تسجيل المشرفين المخفيين في قاعدة البيانات تلقائياً (صامت)
        for admin_id in anonymous_admins:
            await db_add_hidden_admin(chat_id, admin_id, PRIMARY_OWNER_ID)
        
        return anonymous_admins
        
    except Exception as e:
        print(f"⚠️ خطأ في get_anonymous_admins: {e}")
        return []

async def is_authorized_in_group(bot, chat_id: int, user_id: int, update: Update = None) -> bool:
    """
    دالة محسنة للتحقق من الصلاحيات مع دعم:
    1. المطور الأساسي (PRIMARY_OWNER_ID)
    2. المالك المخفي (db_is_hidden_owner)
    3. المشرف المخفي (db_is_hidden_admin)
    4. المشرف المخفي في تيليجرام (Anonymous Admin) عبر update.message.sender_chat
    5. المشرف الحقيقي عبر get_chat_member
    """
    # المطور الأساسي له صلاحية مطلقة في كل مكان
    if user_id == PRIMARY_OWNER_ID:
        return True
    
    cache_key = f"{chat_id}:{user_id}"
    now = time.time()
    
    # التحقق من الكاش
    if cache_key in _admin_cache and (now - _admin_cache_time.get(cache_key, 0)) < _ADMIN_CACHE_TTL:
        return _admin_cache[cache_key]
    
    try:
        # 1. التحقق من المالك المخفي في قاعدة البيانات
        if await db_is_hidden_owner(chat_id, user_id):
            _admin_cache[cache_key] = True
            _admin_cache_time[cache_key] = now
            return True
        
        # 2. التحقق من المشرف المخفي في قاعدة البيانات
        if await db_is_hidden_admin(chat_id, user_id):
            _admin_cache[cache_key] = True
            _admin_cache_time[cache_key] = now
            return True
        
        # 3. التحقق من المشرف المخفي في تيليجرام (Anonymous Admin)
        if update and update.effective_message and update.effective_message.sender_chat:
            sender_chat = update.effective_message.sender_chat
            if sender_chat.id == chat_id:
                try:
                    member = await bot.get_chat_member(chat_id, user_id)
                    if member.status in ['creator', 'administrator']:
                        await db_add_hidden_admin(chat_id, user_id, PRIMARY_OWNER_ID)
                        await invalidate_user_cache(user_id=user_id, chat_id=chat_id)
                        _admin_cache[cache_key] = True
                        _admin_cache_time[cache_key] = now
                        return True
                except Exception as e:
                    print(f"⚠️ خطأ في التحقق من sender_chat: {e}")
        
        # 4. التحقق من المشرف الحقيقي عبر API تيليجرام
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            if member.status in ['creator', 'administrator']:
                await db_add_hidden_admin(chat_id, user_id, PRIMARY_OWNER_ID)
                await invalidate_user_cache(user_id=user_id, chat_id=chat_id)
                _admin_cache[cache_key] = True
                _admin_cache_time[cache_key] = now
                return True
        except Forbidden:
            pass
        except Exception as e:
            print(f"⚠️ خطأ في get_chat_member: {e}")
        
        # 5. محاولة جلب قائمة المشرفين المخفيين
        try:
            anonymous_admins = await get_anonymous_admins(bot, chat_id)
            if user_id in anonymous_admins:
                await db_add_hidden_admin(chat_id, user_id, PRIMARY_OWNER_ID)
                await invalidate_user_cache(user_id=user_id, chat_id=chat_id)
                _admin_cache[cache_key] = True
                _admin_cache_time[cache_key] = now
                return True
        except Exception as e:
            print(f"⚠️ خطأ في get_anonymous_admins: {e}")
        
        _admin_cache[cache_key] = False
        _admin_cache_time[cache_key] = now
        return False
        
    except Exception as e:
        print(f"❌ خطأ في is_authorized_in_group: {e}")
        return False

async def check_admin_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Tuple[bool, str, int]:
    """
    دالة موحدة للتحقق من صلاحيات المشرف.
    تعمل في الخاص والمجموعات مع دعم المشرفين المخفيين.
    """
    if not update or not update.effective_user:
        return False, "❌ لم يتم التعرف على المستخدم", 0
    
    user_id = update.effective_user.id
    chat_id = 0
    
    if update.effective_chat:
        chat_id = update.effective_chat.id
    
    if user_id == PRIMARY_OWNER_ID:
        return True, "", chat_id
    
    if update.effective_chat and update.effective_chat.type == 'private':
        if await is_bot_admin(user_id):
            if context.args and len(context.args) > 0:
                try:
                    potential_chat_id = int(context.args[0])
                    if potential_chat_id < 0:
                        chat_id = potential_chat_id
                    else:
                        if len(str(potential_chat_id)) > 10:
                            chat_id = potential_chat_id
                except ValueError:
                    pass
            
            if chat_id == 0:
                chat_id = context.user_data.get('admin_chat_id', 0)
            
            if chat_id != 0:
                if await is_authorized_in_group(context.bot, chat_id, user_id, update):
                    return True, "", chat_id
                else:
                    return False, "❌ ليس لديك صلاحيات كافية في هذه المجموعة", chat_id
            else:
                return False, "❌ يرجى تحديد معرف المجموعة", 0
        
        return False, "🔒 هذا الأمر للمطور الأساسي أو المشرفين الخارقين فقط", 0
    
    if update.effective_chat and update.effective_chat.type in ['group', 'supergroup']:
        if chat_id == 0:
            return False, "❌ لم يتم تحديد المجموعة", 0
        
        if update.effective_message and update.effective_message.sender_chat:
            sender_chat = update.effective_message.sender_chat
            if sender_chat.id == chat_id:
                await db_add_hidden_admin(chat_id, user_id, PRIMARY_OWNER_ID)
                await invalidate_user_cache(user_id=user_id, chat_id=chat_id)
                return True, "", chat_id
        
        if await is_authorized_in_group(context.bot, chat_id, user_id, update):
            return True, "", chat_id
        
        if await is_telegram_admin(context.bot, chat_id, user_id):
            await db_add_hidden_admin(chat_id, user_id, PRIMARY_OWNER_ID)
            await invalidate_user_cache(user_id=user_id, chat_id=chat_id)
            return True, "", chat_id
        
        return False, "🔒 هذا الأمر للمشرفين فقط", chat_id
    
    return False, "❌ هذا الأمر يعمل فقط في المجموعات", 0

# ===================== دوال استخراج المستخدم المستهدف =====================

async def extract_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Tuple[Optional[int], str]:
    """
    استخراج معرف المستخدم المستهدف بثلاث طرق:
    1. الرد على رسالة المستخدم
    2. كتابة المعرف الرقمي (مثال: 123456789)
    3. كتابة @username (مثال: @username)
    """
    if update.message and update.message.reply_to_message:
        if update.message.reply_to_message.from_user:
            return update.message.reply_to_message.from_user.id, ""
    
    if update.message and update.message.text:
        text = update.message.text
        args = text.split()
        
        if len(args) >= 2:
            target = args[1]
            
            if target.startswith('@'):
                try:
                    chat = await context.bot.get_chat(target)
                    if chat:
                        return chat.id, ""
                except Exception as e:
                    return None, f"❌ لا يمكن العثور على المستخدم {target}"
            
            try:
                user_id = int(target)
                return user_id, ""
            except ValueError:
                pass
    
    return None, "❌ يرجى تحديد المستخدم المستهدف\n\nالطرق المدعومة:\n1. الرد على رسالة المستخدم\n2. كتابة المعرف الرقمي\n3. كتابة @username"

# ===================== دوال أوامر الإدارة =====================

async def ban_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /ban"""
    if update.message is None:
        return
    
    user_id = update.effective_user.id
    
    is_admin, error_msg, chat_id = await check_admin_access(update, context)
    if not is_admin:
        await update.message.reply_text(error_msg)
        return
    
    target_id, error = await extract_target_user(update, context)
    if not target_id:
        await update.message.reply_text(error)
        return
    
    reason = ""
    if update.message.text:
        args = update.message.text.split(maxsplit=2)
        if len(args) >= 3:
            reason = args[2]
    
    if target_id == PRIMARY_OWNER_ID:
        await update.message.reply_text("❌ لا يمكن حظر المطور الأساسي!")
        return
    
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"❌ {bot_perms['reason']}")
        return
    
    success, msg = await execute_ban(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
    await safe_send_markdown(context.bot, chat_id, msg)

async def mute_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /mute"""
    if update.message is None:
        return
    
    user_id = update.effective_user.id
    
    is_admin, error_msg, chat_id = await check_admin_access(update, context)
    if not is_admin:
        await update.message.reply_text(error_msg)
        return
    
    target_id, error = await extract_target_user(update, context)
    if not target_id:
        await update.message.reply_text(error)
        return
    
    reason = ""
    duration_minutes = context.user_data.get('mute_minutes', 60)
    if update.message.text:
        args = update.message.text.split(maxsplit=2)
        if len(args) >= 3:
            try:
                duration_parts = args[2].split(maxsplit=1)
                if duration_parts[0].isdigit():
                    duration_minutes = int(duration_parts[0])
                    if len(duration_parts) > 1:
                        reason = duration_parts[1]
                else:
                    reason = args[2]
            except:
                reason = args[2] if len(args) > 2 else ""
    
    if target_id == PRIMARY_OWNER_ID:
        await update.message.reply_text("❌ لا يمكن كتم المطور الأساسي!")
        return
    
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"❌ {bot_perms['reason']}")
        return
    
    success, msg = await execute_mute(context.bot, chat_id, target_id, duration_minutes, reason=reason, moderator_id=user_id)
    await safe_send_markdown(context.bot, chat_id, msg)

async def unmute_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /unmute"""
    if update.message is None:
        return
    
    user_id = update.effective_user.id
    
    is_admin, error_msg, chat_id = await check_admin_access(update, context)
    if not is_admin:
        await update.message.reply_text(error_msg)
        return
    
    target_id, error = await extract_target_user(update, context)
    if not target_id:
        await update.message.reply_text(error)
        return
    
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"❌ {bot_perms['reason']}")
        return
    
    success, msg = await execute_unmute(context.bot, chat_id, target_id, moderator_id=user_id)
    await safe_send_markdown(context.bot, chat_id, msg)

async def warn_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /warn"""
    if update.message is None:
        return
    
    user_id = update.effective_user.id
    
    is_admin, error_msg, chat_id = await check_admin_access(update, context)
    if not is_admin:
        await update.message.reply_text(error_msg)
        return
    
    target_id, error = await extract_target_user(update, context)
    if not target_id:
        await update.message.reply_text(error)
        return
    
    reason = ""
    if update.message.text:
        args = update.message.text.split(maxsplit=2)
        if len(args) >= 3:
            reason = args[2]
    
    if target_id == PRIMARY_OWNER_ID:
        await update.message.reply_text("❌ لا يمكن تحذير المطور الأساسي!")
        return
    
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"❌ {bot_perms['reason']}")
        return
    
    success, msg = await execute_warn(context.bot, chat_id, target_id, user_id, reason=reason)
    await safe_send_markdown(context.bot, chat_id, msg)

async def kick_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /kick"""
    if update.message is None:
        return
    
    user_id = update.effective_user.id
    
    is_admin, error_msg, chat_id = await check_admin_access(update, context)
    if not is_admin:
        await update.message.reply_text(error_msg)
        return
    
    target_id, error = await extract_target_user(update, context)
    if not target_id:
        await update.message.reply_text(error)
        return
    
    reason = ""
    if update.message.text:
        args = update.message.text.split(maxsplit=2)
        if len(args) >= 3:
            reason = args[2]
    
    if target_id == PRIMARY_OWNER_ID:
        await update.message.reply_text("❌ لا يمكن طرد المطور الأساسي!")
        return
    
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"❌ {bot_perms['reason']}")
        return
    
    success, msg = await execute_kick(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
    await safe_send_markdown(context.bot, chat_id, msg)

async def restrict_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /restrict"""
    if update.message is None:
        return
    
    user_id = update.effective_user.id
    
    is_admin, error_msg, chat_id = await check_admin_access(update, context)
    if not is_admin:
        await update.message.reply_text(error_msg)
        return
    
    target_id, error = await extract_target_user(update, context)
    if not target_id:
        await update.message.reply_text(error)
        return
    
    reason = ""
    if update.message.text:
        args = update.message.text.split(maxsplit=2)
        if len(args) >= 3:
            reason = args[2]
    
    if target_id == PRIMARY_OWNER_ID:
        await update.message.reply_text("❌ لا يمكن تقييد المطور الأساسي!")
        return
    
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"❌ {bot_perms['reason']}")
        return
    
    success, msg = await execute_restrict(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
    await safe_send_markdown(context.bot, chat_id, msg)

async def pin_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /pin"""
    if update.message is None:
        return
    
    user_id = update.effective_user.id
    
    is_admin, error_msg, chat_id = await check_admin_access(update, context)
    if not is_admin:
        await update.message.reply_text(error_msg)
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ يرجى الرد على الرسالة التي تريد تثبيتها")
        return
    
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"❌ {bot_perms['reason']}")
        return
    
    success, msg = await execute_pin(context.bot, chat_id, update.message.reply_to_message.message_id)
    await safe_send_markdown(context.bot, chat_id, msg)

async def unban_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /unban"""
    if update.message is None:
        return
    
    user_id = update.effective_user.id
    
    is_admin, error_msg, chat_id = await check_admin_access(update, context)
    if not is_admin:
        await update.message.reply_text(error_msg)
        return
    
    target_id, error = await extract_target_user(update, context)
    if not target_id:
        await update.message.reply_text(error)
        return
    
    if target_id == PRIMARY_OWNER_ID:
        await update.message.reply_text("❌ لا يمكن إلغاء حظر المطور الأساسي!")
        return
    
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"❌ {bot_perms['reason']}")
        return
    
    success, msg = await execute_unban(context.bot, chat_id, target_id, moderator_id=user_id)
    await safe_send_markdown(context.bot, chat_id, msg)

# ===================== دوال أوامر الإدارة الإضافية =====================

async def lock_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /lock"""
    if update.message is None:
        return
    
    user_id = update.effective_user.id
    
    is_admin, error_msg, chat_id = await check_admin_access(update, context)
    if not is_admin:
        await update.message.reply_text(error_msg)
        return
    
    await db_set_chat_lock(chat_id, True, user_id)
    await update.message.reply_text(get_text(user_id, 'locked'))

async def unlock_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /unlock"""
    if update.message is None:
        return
    
    user_id = update.effective_user.id
    
    is_admin, error_msg, chat_id = await check_admin_access(update, context)
    if not is_admin:
        await update.message.reply_text(error_msg)
        return
    
    await db_set_chat_lock(chat_id, False)
    await update.message.reply_text(get_text(user_id, 'unlocked'))

async def syncgroup_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج /syncgroup - تسجيل المجموعة بصمت"""
    if update.message is None:
        return
    
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    
    chat_id = chat.id
    chat_name = chat.title or "بدون اسم"
    user_id = user.id
    
    await db_register_group(chat_id, chat_name, user_id, chat.username)
    
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"⚠️ **تنبيه:**\n{bot_perms['reason']}\n\nيرجى منح البوت الصلاحيات المطلوبة.")
        return
    
    if await is_telegram_admin(context.bot, chat_id, user_id):
        await db_register_hidden_owner_group(chat_id, user_id)
        await invalidate_user_cache(user_id=user_id, chat_id=chat_id)
    
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        for admin in admins:
            if admin.status in ['creator', 'administrator'] and not admin.user.is_bot:
                await db_add_hidden_admin(chat_id, admin.user.id, PRIMARY_OWNER_ID)
        await invalidate_user_cache(chat_id=chat_id)
    except Exception as e:
        print(f"⚠️ خطأ في تسجيل المشرفين: {e}")
    
    await update.message.reply_text(
        f"✅ **تم تفعيل المجموعة بنجاح!**\n\n"
        f"📌 اسم المجموعة: {chat_name}\n"
        f"🆔 المعرف: {chat_id}\n\n"
        f"🔐 استخدم /security لإعدادات الأمان\n"
        f"🛠️ استخدم /panel للوحة التحكم",
        parse_mode="MarkdownV2"
    )

# ===================== دوال أوامر المشرفين المخفيين =====================

async def register_hidden_owner_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج /register_hidden_owner - تسجيل مالك مخفي (صامت)"""
    if update.message is None:
        return
    
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ يعمل فقط في المجموعات")
        return
    
    chat_id = chat.id
    user_id = user.id
    
    if not await is_telegram_admin(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    if await db_is_hidden_owner(chat_id, user_id):
        await update.message.reply_text("⚠️ أنت مسجل بالفعل كمالك مخفي")
        return
    
    await db_register_hidden_owner_group(chat_id, user_id)
    await invalidate_user_cache(user_id=user_id, chat_id=chat_id)
    await update.message.reply_text("✅ **تم تسجيلك كمالك مخفي بنجاح**")

async def add_hidden_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج /add_hidden_admin - إضافة مشرف مخفي"""
    if update.message is None:
        return
    
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    
    chat_id = chat.id
    user_id = user.id
    
    if not await is_telegram_admin(context.bot, chat_id, user_id) and not await db_is_hidden_owner(chat_id, user_id):
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
    
    if await db_is_hidden_admin(chat_id, target_id):
        await update.message.reply_text(f"⚠️ المستخدم `{target_id}` مشرف مخفي بالفعل!")
        return
    
    success = await db_add_hidden_admin(chat_id, target_id, user_id)
    if success:
        await invalidate_user_cache(user_id=target_id, chat_id=chat_id)
        await update.message.reply_text(f"✅ تم إضافة المشرف المخفي `{target_id}` بنجاح")
    else:
        await update.message.reply_text("❌ فشل إضافة المشرف المخفي!")

async def remove_hidden_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج /remove_hidden_admin - إزالة مشرف مخفي"""
    if update.message is None:
        return
    
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    
    chat_id = chat.id
    user_id = user.id
    
    if not await is_telegram_admin(context.bot, chat_id, user_id) and not await db_is_hidden_owner(chat_id, user_id):
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
        await invalidate_user_cache(user_id=target_id, chat_id=chat_id)
        await update.message.reply_text(f"✅ تم إزالة المشرف المخفي `{target_id}` بنجاح")
    else:
        await update.message.reply_text("❌ فشل إزالة المشرف المخفي!")

async def list_hidden_admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج /list_hidden_admins - عرض المشرفين المخفيين"""
    if update.message is None:
        return
    
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    
    chat_id = chat.id
    user_id = user.id
    
    if not await is_telegram_admin(context.bot, chat_id, user_id) and not await db_is_hidden_owner(chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    admins = await db_get_hidden_admins(chat_id)
    if not admins:
        await update.message.reply_text("📭 لا يوجد مشرفين مخفيين في هذه المجموعة")
        return
    
    text = "🔒 **قائمة المشرفين المخفيين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for admin in admins:
        text += f"👤 المستخدم: `{admin['admin_id']}`\n"
        text += f"➕ أضيف بواسطة: `{admin['added_by']}`\n"
        text += f"🕐 التاريخ: {admin['added_at'][:16]}\n"
        text += "━━━━━━━━━━━━━━━━━━━━━━\n"
    
    await update.message.reply_text(text, parse_mode="MarkdownV2")

# ===================== دوال أوامر أخرى =====================

async def panel_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج /panel - لوحة التحكم"""
    if update.message is None:
        return
    
    user_id = update.effective_user.id
    
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_id = update.effective_chat.id
        is_admin, error_msg, _ = await check_admin_access(update, context)
        if not is_admin:
            await update.message.reply_text(error_msg)
            return
        
        current_lock_status = await is_chat_locked(chat_id)
        lock_status_text = "🔒 مقفلة" if current_lock_status else "🔓 مفتوحة"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔒 قفل المجموعة", callback_data=f"panel_lock:{chat_id}"),
             InlineKeyboardButton("🔓 فتح المجموعة", callback_data=f"panel_unlock:{chat_id}")],
            [InlineKeyboardButton("🛠️ إجراءات متقدمة", callback_data=f"advanced_actions:{chat_id}"),
             InlineKeyboardButton("🔙 إغلاق اللوحة", callback_data="panel_close")]
        ])
        
        await update.message.reply_text(
            f"🔧 **لوحة تحكم المجموعة**\n━━━━━━━━━━━━━━\n"
            f"📌 **المجموعة:** {update.effective_chat.title}\n"
            f"🔐 **الحالة:** {lock_status_text}\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"استخدم الأزرار للتحكم في قفل وفتح المجموعة والإجراءات المتقدمة",
            reply_markup=kb,
            parse_mode="MarkdownV2"
        )
        return
    
    groups = await db_get_user_groups(user_id)
    if not groups:
        await update.message.reply_text(
            "📭 لا توجد مجموعات مسجلة.\n\n"
            "📌 **لتفعيل البوت:**\n"
            "1. أضف البوت إلى مجموعتك\n"
            "2. اجعل البوت مشرفاً\n"
            "3. استخدم الأمر /syncgroup في المجموعة"
        )
        return
    
    keyboard = []
    for gid, gname, _, _ in groups:
        is_locked = await is_chat_locked(gid)
        icon = "🔒" if is_locked else "🔓"
        keyboard.append([InlineKeyboardButton(f"{icon} {gname[:30]}", callback_data=f"advanced_actions:{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back")])
    
    await update.message.reply_text(
        "🔧 **لوحة التحكم**\nاختر مجموعة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ===================== دوال معالجات الأزرار الإضافية =====================

async def star_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    معالج زر النجوم - يرسل رسالة ترحيب للمستخدم
    """
    query = update.callback_query
    if query:
        try:
            await query.answer()  # تأكيد استلام الكولباك
        except Exception as e:
            print(f"فشل تأكيد الكولباك: {e}")
    
    try:
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "صديقنا"
        
        # كيبورد تقييم
        rating_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⭐", callback_data="rating_1"),
                InlineKeyboardButton("⭐⭐", callback_data="rating_2"),
                InlineKeyboardButton("⭐⭐⭐", callback_data="rating_3"),
                InlineKeyboardButton("⭐⭐⭐⭐", callback_data="rating_4"),
                InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data="rating_5")
            ],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
        ])
        
        await safe_send_markdown(
            context.bot,
            user_id,
            f"⭐ **مرحباً بك في ريلاكس مانيجر يا {user_name}!**\n\n"
            f"📌 استخدم /start للقائمة الرئيسية\n"
            f"📌 استخدم /help للمساعدة\n"
            f"📌 استخدم /trial للتجربة المجانية\n\n"
            f"⭐ **قيم البوت:**",
            reply_markup=rating_keyboard
        )
        
        print(f"✅ تم تفعيل زر النجوم للمستخدم {user_id}")
        
    except Exception as e:
        error_id = log_error(e, {
            'user_id': user_id if 'user_id' in locals() else None,
            'action': 'star_button'
        })
        print(f"❌ خطأ في star_button (الرمز: {error_id}): {e}")

async def help_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    معالج زر المساعدة - يرسل رسالة مساعدة للمستخدم
    """
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except Exception as e:
            print(f"فشل تأكيد الكولباك: {e}")
    
    try:
        user_id = update.effective_user.id
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 إحصائياتي", callback_data="btn_stats"),
             InlineKeyboardButton("📡 قنواتي", callback_data="btn_channels")],
            [InlineKeyboardButton("⚙️ الإعدادات", callback_data="btn_settings"),
             InlineKeyboardButton("❓ المساعدة", callback_data="btn_help")],
            [InlineKeyboardButton("🎁 تجربة مجانية", callback_data="btn_trial"),
             InlineKeyboardButton("💎 اشتراك", callback_data="btn_subscribe")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
        ])
        
        await safe_send_markdown(
            context.bot,
            user_id,
            "❓ **مركز المساعدة**\n\n"
            "📌 **الأوامر المتاحة:**\n"
            "• /start - القائمة الرئيسية\n"
            "• /help - هذه المساعدة\n"
            "• /trial - تجربة مجانية\n"
            "• /subscribe - الاشتراك\n"
            "• /support - مركز الدعم\n"
            "• /developer - معلومات المطور\n\n"
            "📌 **للمشرفين:**\n"
            "• /security - إعدادات الأمان\n"
            "• /panel - لوحة التحكم\n"
            "• /ban - حظر مستخدم\n"
            "• /mute - كتم مستخدم\n\n"
            "💡 للمزيد من المعلومات، تواصل مع الدعم.",
            reply_markup=keyboard
        )
        
        print(f"✅ تم تفعيل زر المساعدة للمستخدم {user_id}")
        
    except Exception as e:
        error_id = log_error(e, {
            'user_id': user_id if 'user_id' in locals() else None,
            'action': 'help_button'
        })
        print(f"❌ خطأ في help_button (الرمز: {error_id}): {e}")

async def rating_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    معالج التقييم - يستقبل التقييم من المستخدم
    """
    query = update.callback_query
    if query:
        try:
            rating = query.data.replace("rating_", "")
            stars = "⭐" * int(rating)
            await query.answer(f"شكراً لك! {stars}")
            
            await safe_send_markdown(
                context.bot,
                update.effective_user.id,
                f"✅ **شكراً لتقييمك!**\n\n"
                f"تقييمك: {stars}\n\n"
                f"نتمنى أن نكون عند حسن ظنك 🤍"
            )
        except Exception as e:
            print(f"خطأ في معالج التقييم: {e}")

async def custom_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    معالج عام للأزرار المخصصة - يمكن تخصيصه حسب الحاجة
    """
    query = update.callback_query
    if not query:
        return
    
    try:
        await query.answer()
        data = query.data
        user_id = update.effective_user.id
        
        # معالجة الأزرار حسب البيانات
        if data.startswith("btn_"):
            action = data.replace("btn_", "")
            
            if action == "start":
                await start_command_handler(update, context)
            elif action == "help":
                await help_command_handler(update, context)
            elif action == "trial":
                await trial_command_handler(update, context)
            elif action == "support":
                await support_command_handler(update, context)
            elif action == "developer":
                await developer_command_handler(update, context)
            elif action == "stats":
                await stats_command_handler(update, context)
            elif action == "channels":
                await my_channels_callback(update, context)
            elif action == "settings":
                await settings_menu_callback(update, context)
            elif action == "subscribe":
                await subscribe_menu_callback(update, context)
            else:
                await query.edit_message_text(f"⚠️ الزر '{action}' غير معروف")
                
    except Exception as e:
        error_id = log_error(e, {
            'user_id': update.effective_user.id if update.effective_user else None,
            'action': 'custom_button'
        })
        print(f"❌ خطأ في custom_button (الرمز: {error_id}): {e}")

async def inline_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    معالج الكيبورد المضمن - يعرض أزرار تفاعلية
    """
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except:
            pass
    
    try:
        user_id = update.effective_user.id
        
        # إنشاء كيبورد مخصص
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📊 إحصائياتي", callback_data="btn_stats"),
                InlineKeyboardButton("📡 قنواتي", callback_data="btn_channels")
            ],
            [
                InlineKeyboardButton("⚙️ الإعدادات", callback_data="btn_settings"),
                InlineKeyboardButton("❓ المساعدة", callback_data="btn_help")
            ],
            [
                InlineKeyboardButton("🎁 تجربة مجانية", callback_data="btn_trial"),
                InlineKeyboardButton("💎 اشتراك", callback_data="btn_subscribe")
            ],
            [
                InlineKeyboardButton("⭐ تقييم", callback_data="star_rating"),
                InlineKeyboardButton("📞 دعم", callback_data="btn_support")
            ]
        ])
        
        await safe_send_markdown(
            context.bot,
            user_id,
            "🌟 **مرحباً بك في ريلاكس مانيجر!**\n\n"
            "اختر ما تريد فعله من الأزرار أدناه:",
            reply_markup=keyboard
        )
        
    except Exception as e:
        error_id = log_error(e, {
            'user_id': update.effective_user.id if update.effective_user else None,
            'action': 'inline_keyboard'
        })
        print(f"❌ خطأ في inline_keyboard (الرمز: {error_id}): {e}")

async def quick_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    معالج الردود السريعة - يرسل ردود مخصصة بناءً على الكلمات المفتاحية
    """
    if not update.message or not update.message.text:
        return
    
    text = update.message.text.lower().strip()
    user_id = update.effective_user.id
    
    # قاموس الردود السريعة
    quick_replies = {
        "مرحباً": "أهلاً وسهلاً بك في ريلاكس مانيجر 🤍",
        "السلام عليكم": "وعليكم السلام ورحمة الله وبركاته 🌹",
        "شكراً": "العفو، تحت أمرك دائماً ❤️",
        "كيف حالك": "الحمد لله بخير، كيفك أنت؟ 🌸",
        "help": "استخدم /help للحصول على المساعدة",
        "start": "استخدم /start للقائمة الرئيسية",
        "تقييم": "⭐ استخدم زر التقييم في القائمة الرئيسية",
        "دعم": "📞 استخدم /support للتواصل مع الدعم"
    }
    
    # البحث عن رد مناسب
    for keyword, reply in quick_replies.items():
        if keyword in text:
            try:
                await update.message.reply_text(reply)
                print(f"✅ تم إرسال رد سريع للمستخدم {user_id}: {keyword}")
            except Exception as e:
                print(f"❌ خطأ في الرد السريع: {e}")
            break

# ===================== دوال الأوامر الأساسية =====================

async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /start"""
    user = update.effective_user
    if not user:
        return
    
    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or ""
    
    await db_register_user(user_id)
    await db_update_user_cache(user_id, username, first_name)
    
    await main_menu_callback(update, context)

async def help_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /help"""
    user_id = update.effective_user.id
    await update.message.reply_text(get_text(user_id, 'help'), parse_mode="MarkdownV2")

async def support_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /support"""
    user_id = update.effective_user.id
    context.user_data['support_mode'] = True
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 كتابة تذكرة", callback_data=CallbackData.SUPPORT_TICKET)],
        [InlineKeyboardButton("❓ المساعدة", callback_data=CallbackData.SUPPORT_HELP)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await update.message.reply_text(get_text(user_id, 'support_welcome'), reply_markup=keyboard)

async def trial_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /trial"""
    await trial_callback(update, context)

async def subscribe_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /subscribe"""
    await subscribe_menu_callback(update, context)

async def developer_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /developer"""
    await developer_callback(update, context)

async def updates_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /updates"""
    await updates_callback(update, context)

async def stats_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /stats"""
    if update.message is None:
        return
    uid = update.effective_user.id
    await update.message.reply_text("📊 **جاري تحميل الإحصائيات...**", parse_mode="MarkdownV2")
    # سيتم استكمالها في الملف الرئيسي

async def language_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /language"""
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

# ===================== دوال الكولباك الأساسية =====================

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج القائمة الرئيسية"""
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except:
            pass
    uid = update.effective_user.id
    # سيتم استكمالها في الملف الرئيسي

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج زر الرجوع"""
    await main_menu_callback(update, context)

async def trial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج زر التجربة المجانية"""
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except:
            pass
    uid = update.effective_user.id
    # سيتم استكمالها في الملف الرئيسي

async def subscribe_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج قائمة الاشتراك"""
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except:
            pass
    uid = update.effective_user.id
    # سيتم استكمالها في الملف الرئيسي

async def developer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج زر المطور"""
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except:
            pass
    uid = update.effective_user.id
    # سيتم استكمالها في الملف الرئيسي

async def updates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج زر التحديثات"""
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except:
            pass
    uid = update.effective_user.id
    # سيتم استكمالها في الملف الرئيسي

async def my_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج زر قنواتي"""
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except:
            pass
    uid = update.effective_user.id
    # سيتم استكمالها في الملف الرئيسي

async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج زر الإعدادات"""
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except:
            pass
    uid = update.effective_user.id
    # سيتم استكمالها في الملف الرئيسي

# ===================== تصدير الدوال =====================

__all__ = [
    # دوال التحقق من الصلاحيات
    'is_telegram_admin',
    'get_anonymous_admins',
    'is_authorized_in_group',
    'check_admin_access',
    'extract_target_user',
    
    # دوال أوامر الإدارة
    'ban_command_handler',
    'mute_command_handler',
    'unmute_command_handler',
    'warn_command_handler',
    'kick_command_handler',
    'restrict_command_handler',
    'pin_command_handler',
    'unban_command_handler',
    'lock_command_handler',
    'unlock_command_handler',
    'syncgroup_command_handler',
    
    # دوال أوامر المشرفين المخفيين
    'register_hidden_owner_handler',
    'add_hidden_admin_command',
    'remove_hidden_admin_command',
    'list_hidden_admins_command',
    
    # دوال الأوامر الأساسية
    'start_command_handler',
    'help_command_handler',
    'support_command_handler',
    'trial_command_handler',
    'subscribe_command_handler',
    'developer_command_handler',
    'updates_command_handler',
    'stats_command_handler',
    'language_command_handler',
    'panel_command_handler',
    
    # دوال معالجات الأزرار
    'star_button_handler',
    'help_button_handler',
    'rating_handler',
    'custom_button_handler',
    'inline_keyboard_handler',
    'quick_reply_handler',
    
    # دوال الكولباك الأساسية
    'main_menu_callback',
    'back_callback',
    'trial_callback',
    'subscribe_menu_callback',
    'developer_callback',
    'updates_callback',
    'my_channels_callback',
    'settings_menu_callback',
]

print("✅ تم تحميل handlers.py بنجاح!")
