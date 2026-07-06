from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_USERNAME

def main_menu(user_id, is_admin=False):
    kb = [
        [InlineKeyboardButton("👥 مجموعاتي", callback_data="groups"),
         InlineKeyboardButton("➕ قناة", callback_data="add_channel")],
        [InlineKeyboardButton("📡 قنواتي", callback_data="channels"),
         InlineKeyboardButton("⚙️ إعدادات", callback_data="settings")],
        [InlineKeyboardButton("📥 15 منشور", callback_data="add_posts"),
         InlineKeyboardButton("📤 نشر واحد", callback_data="publish_one")],
        [InlineKeyboardButton("📋 منشوراتي", callback_data="posts"),
         InlineKeyboardButton("♻️ تدوير", callback_data="recycle")],
        [InlineKeyboardButton("📊 إحصائيات", callback_data="stats"),
         InlineKeyboardButton("📈 كامل", callback_data="full_stats")],
        [InlineKeyboardButton("🏆 مسابقات", callback_data="contests"),
         InlineKeyboardButton("🔗 إحالات", callback_data="referral")],
        [InlineKeyboardButton("⏰ تذكيرات", callback_data="reminders"),
         InlineKeyboardButton("🌐 ترجمة", callback_data="translate")],
        [InlineKeyboardButton("🏆 أفضل 10", callback_data="top"),
         InlineKeyboardButton("📊 رتبتي", callback_data="rank")],
        [InlineKeyboardButton("🎁 تجربة", callback_data="trial"),
         InlineKeyboardButton("💎 اشتراك", callback_data="subscribe")],
        [InlineKeyboardButton("❓ مساعدة", callback_data="help"),
         InlineKeyboardButton("🌐 لغة", callback_data="language")],
        [InlineKeyboardButton("➕ أضف لمجموعة", url=f"https://t.me/{BOT_USERNAME}?startgroup")],
    ]
    if is_admin:
        kb.append([InlineKeyboardButton("👑 أدمن", callback_data="admin")])
    return InlineKeyboardMarkup(kb)

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 مستخدمين", callback_data="adm_users"),
         InlineKeyboardButton("🚫 محظورين", callback_data="adm_banned")],
        [InlineKeyboardButton("📡 قنوات", callback_data="adm_channels"),
         InlineKeyboardButton("📊 مجموعات", callback_data="adm_groups")],
        [InlineKeyboardButton("💬 ردود", callback_data="adm_replies"),
         InlineKeyboardButton("📋 تذاكر", callback_data="adm_tickets")],
        [InlineKeyboardButton("➕ رد", callback_data="adm_addreply"),
         InlineKeyboardButton("🗑️ حذف رد", callback_data="adm_delreply")],
        [InlineKeyboardButton("🏆 مسابقة", callback_data="adm_contest"),
         InlineKeyboardButton("📨 إذاعة", callback_data="adm_broadcast")],
        [InlineKeyboardButton("💾 نسخ", callback_data="adm_backup"),
         InlineKeyboardButton("📥 تصدير", callback_data="adm_export")],
        [InlineKeyboardButton("🔙", callback_data="back")],
    ])
