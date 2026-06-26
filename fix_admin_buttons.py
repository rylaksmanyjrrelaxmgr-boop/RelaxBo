#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
إصلاح أزرار الأدمن في بوت ريلاكس مانيجر
"""

import re
import os

def fix_admin_buttons():
    """إصلاح دالة get_admin_keyboard"""
    
    file_path = "reelax_bot.py"
    
    if not os.path.exists(file_path):
        print("❌ ملف reelax_bot.py غير موجود!")
        return False
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # البحث عن دالة get_admin_keyboard القديمة
    old_pattern = r'def get_admin_keyboard\(user_id: int\) -> InlineKeyboardMarkup:.*?return InlineKeyboardMarkup\(\[.*?\]\)'
    
    # الدالة الجديدة المصححة
    new_function = '''def get_admin_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """لوحة تحكم الأدمن - نسخة مصححة"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    def esc(text):
        """تخطي الأحرف الخاصة"""
        if not text:
            return ""
        special = r'_*[]()~`>#+\\-=|{}.!'
        for char in special:
            text = text.replace(char, f'\\\\{char}')
        text = re.sub(r'(\\d+)\\.', r'\\1\\.', text)
        return text
    
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(esc(get_text(user_id, "admin_users")), callback_data="admin:users"),
            InlineKeyboardButton(esc(get_text(user_id, "admin_banned")), callback_data="admin:banned_users")
        ],
        [
            InlineKeyboardButton(esc(get_text(user_id, "admin_channels")), callback_data="admin:all_channels"),
            InlineKeyboardButton(esc("⛔ قنوات محظورة"), callback_data="admin:banned_channels")
        ],
        [
            InlineKeyboardButton(esc("📊 المجموعات"), callback_data="admin:groups"),
            InlineKeyboardButton(esc("🚷 مجموعات محظورة"), callback_data="admin:banned_groups")
        ],
        [
            InlineKeyboardButton(esc("📢 قنوات البوت"), callback_data="admin:bot_channels"),
            InlineKeyboardButton(esc("🚫 قنوات بوت محظورة"), callback_data="admin:banned_bot_channels")
        ],
        [
            InlineKeyboardButton(esc("❤️ تنشيط الكل"), callback_data="admin:activate_all_channels"),
            InlineKeyboardButton(esc("📂 مراقبة المستخدمين"), callback_data="admin:monitor_users")
        ],
        [
            InlineKeyboardButton(esc("👑 + مشرف"), callback_data="admin:add_admin"),
            InlineKeyboardButton(esc("🗑️ - مشرف"), callback_data="admin:remove_admin")
        ],
        [
            InlineKeyboardButton(esc("💬 ردود المجموعة"), callback_data="admin:replies"),
            InlineKeyboardButton(esc("🚫 كلمات محظورة (عامة)"), callback_data="admin:banned_words")
        ],
        [
            InlineKeyboardButton(esc("🛠️ إجراءات متقدمة"), callback_data="advanced_actions:0")
        ],
        [
            InlineKeyboardButton(esc("🖥️ حالة الرام"), callback_data="admin:ram"),
            InlineKeyboardButton(esc("📊 إحصائيات عامة"), callback_data="admin:stats")
        ],
        [
            InlineKeyboardButton(esc("📈 مقاييس الأداء"), callback_data="admin:metrics")
        ],
        [
            InlineKeyboardButton(esc("💾 نسخة احتياطية"), callback_data="admin:backup"),
            InlineKeyboardButton(esc("🔄 استعادة نسخة"), callback_data="admin:restore_backup")
        ],
        [
            InlineKeyboardButton(esc("⏱️ وقت النشر (عام)"), callback_data="admin:change_interval"),
            InlineKeyboardButton(esc("⚙️ إعدادات النسخ"), callback_data="admin:backup_settings")
        ],
        [
            InlineKeyboardButton(esc("📢 نشر تحديث"), callback_data="admin:send_update"),
            InlineKeyboardButton(esc("⚙️ قناة التحديثات"), callback_data="admin:set_update_channel")
        ],
        [
            InlineKeyboardButton(esc("📢 عرض القناة الحالية"), callback_data="admin:show_update_channel")
        ],
        [
            InlineKeyboardButton(esc("🔄 التحديثات"), callback_data="admin:updates"),
            InlineKeyboardButton(esc("🔒 الاشتراك الإجباري"), callback_data="admin:force_subscribe")
        ],
        [
            InlineKeyboardButton(esc("⚙️ تعيين القناة"), callback_data="admin:set_force_channel"),
            InlineKeyboardButton(esc("📨 إرسال رسالة"), callback_data="admin:broadcast")
        ],
        [
            InlineKeyboardButton(esc("📋 تذاكر الدعم"), callback_data="admin:support_tickets"),
            InlineKeyboardButton(esc("🗑️ حذف جميع التذاكر"), callback_data="admin:delete_all_tickets")
        ],
        [
            InlineKeyboardButton(esc("📁 صلاحية /sendcode"), callback_data="admin:manage_sendcode"),
            InlineKeyboardButton(esc("📋 قناة التقارير"), callback_data="admin:show_log_channel")
        ],
        [
            InlineKeyboardButton(esc("📋 تعيين قناة التقارير"), callback_data="admin:set_log_channel")
        ],
        [
            InlineKeyboardButton(esc("🚫 حظر قناة"), callback_data="ban_channel"),
            InlineKeyboardButton(esc("✅ إلغاء حظر قناة"), callback_data="unban_channel")
        ],
        [
            InlineKeyboardButton(esc("📋 القنوات المحظورة"), callback_data="banned_channels")
        ],
        [
            InlineKeyboardButton(esc(get_text(user_id, "back")), callback_data="back")
        ]
    ])'''
    
    # استبدال الدالة القديمة بالجديدة
    content = re.sub(old_pattern, new_function, content, flags=re.DOTALL)
    
    # إذا لم يتم العثور على الدالة، أضفها في نهاية الملف
    if "def get_admin_keyboard" not in content:
        content += "\n\n" + new_function
        print("✅ تم إضافة دالة get_admin_keyboard")
    
    # حفظ الملف
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ تم إصلاح أزرار الأدمن بنجاح!")
    return True

if __name__ == "__main__":
    fix_admin_buttons()
