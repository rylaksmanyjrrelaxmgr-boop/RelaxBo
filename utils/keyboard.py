from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from core.db_queries import db_get_channels, db_get_active_channel, db_get_unpublished_count
from core.translation import get_text

async def get_main_keyboard(user_id: int):
    channels = await db_get_channels(user_id)
    active = await db_get_active_channel(user_id)
    unpublished = await db_get_unpublished_count(active) if active else 0
    
    # ✅ الأزرار الأساسية (تظهر دائماً)
    keyboard = [
        [InlineKeyboardButton("👥 مجموعاتي", callback_data="groups:my_groups"),
         InlineKeyboardButton("➕ إضافة قناة", callback_data="channels:add")],
        [InlineKeyboardButton("📡 قنواتي", callback_data="channels:my"),
         InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings:menu")],
    ]
    
    # ✅ أزرار القناة (تظهر إذا كان عندك قناة)
    if channels:
        keyboard.append([
            InlineKeyboardButton("📥 إضافة 15 منشور", callback_data="posts:add_15"),
            InlineKeyboardButton("📤 نشر واحد", callback_data="posts:publish_one")
        ])
        keyboard.append([
            InlineKeyboardButton("📋 منشوراتي", callback_data="posts:my_posts"),
            InlineKeyboardButton("♻️ إعادة تدوير", callback_data="posts:recycle")
        ])
        keyboard.append([
            InlineKeyboardButton(f"📊 إحصائياتي ({unpublished})", callback_data="stats:pending"),
            InlineKeyboardButton("📈 إحصائيات كاملة", callback_data="stats:full")
        ])
        keyboard.append([
            InlineKeyboardButton("⏰ الجدولة", callback_data="schedule:menu"),
            InlineKeyboardButton("📊 إحصائيات القناة", callback_data="channel_stats")
        ])
        keyboard.append([
            InlineKeyboardButton("📤 نشر الكل", callback_data="publish_all")
        ])
    
    # ✅ الأزرار العامة
    keyboard.append([
        InlineKeyboardButton("🎁 تجربة مجانية", callback_data="trial"),
        InlineKeyboardButton("💎 اشتراك", callback_data="subscribe")
    ])
    keyboard.append([
        InlineKeyboardButton("❓ المساعدة", callback_data="help"),
        InlineKeyboardButton("🌐 اللغة", callback_data="language")
    ])
    keyboard.append([
        InlineKeyboardButton("🔗 الإحالات", callback_data="referral:menu"),
        InlineKeyboardButton("⏰ التذكيرات", callback_data="reminder:menu")
    ])
    keyboard.append([
        InlineKeyboardButton("🌐 الترجمة", callback_data="translation:menu"),
        InlineKeyboardButton("📞 الدعم", callback_data="support:menu")
    ])
    keyboard.append([
        InlineKeyboardButton("👨‍💻 المطور", callback_data="developer"),
        InlineKeyboardButton("📢 التحديثات", callback_data="updates")
    ])
    keyboard.append([
        InlineKeyboardButton("🏆 المسابقات", callback_data="contests_menu")
    ])
    
    # ✅ أزرار المشرفين (للمطور فقط)
    if user_id == MAIN_ADMIN_ID:
        keyboard.append([
            InlineKeyboardButton("👑 لوحة الأدمن", callback_data="admin:panel")
        ])
    
    return InlineKeyboardMarkup(keyboard), "🌿 **مرحباً بك في ريلاكس مانيجر**\nاختر الإجراء المناسب:"
