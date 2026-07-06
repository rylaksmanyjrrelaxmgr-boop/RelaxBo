from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from core.db_queries import db_get_channels, db_get_active_channel, db_get_unpublished_count
from core.translation import get_text

async def get_main_keyboard(user_id: int):
    channels = await db_get_channels(user_id)
    active = await db_get_active_channel(user_id)
    unpublished = await db_get_unpublished_count(active) if active else 0
    
    keyboard = [
        [InlineKeyboardButton("👥 مجموعاتي", callback_data="groups:my_groups"),
         InlineKeyboardButton("➕ إضافة قناة", callback_data="channels:add")],
        [InlineKeyboardButton("📡 قنواتي", callback_data="channels:my"),
         InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings:menu")],
    ]
    
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
        InlineKeyboardButton("❓ المساعدة", callback_data="help"),
        InlineKeyboardButton("🎁 تجربة مجانية", callback_data="trial")
    ])
    keyboard.append([
        InlineKeyboardButton("💎 اشتراك", callback_data="subscribe"),
        InlineKeyboardButton("🌐 اللغة", callback_data="language")
    ])
    
    return InlineKeyboardMarkup(keyboard), "🌿 **مرحباً بك في ريلاكس مانيجر**\nاختر الإجراء المناسب:"
