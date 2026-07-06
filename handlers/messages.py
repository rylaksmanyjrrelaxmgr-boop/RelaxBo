from telegram import Update
from telegram.ext import ContextTypes
from core.db_queries import *
from core.translation import get_text
from handlers.callbacks import main_menu_callback

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text or ""
    state = context.user_data.get("state")
    
    if text == "/cancel":
        context.user_data.pop("state", None)
        await update.message.reply_text(get_text(user_id, "cancelled"))
        await main_menu_callback(update, context)
        return
    
    if state == "WAITING_CHANNEL_ID":
        channel_id = text.strip()
        if not channel_id.startswith("@") and not channel_id.startswith("-100"):
            await update.message.reply_text("❌ معرف قناة غير صالح!")
            return
        new_id = await db_add_channel(user_id, channel_id, channel_id)
        if new_id:
            await db_set_active_channel(user_id, new_id)
            await update.message.reply_text(f"✅ تم إضافة القناة: {channel_id}")
        else:
            await update.message.reply_text("⚠️ القناة موجودة مسبقاً")
        context.user_data.pop("state", None)
        await main_menu_callback(update, context)
        return
    
    if state == "ADDING_POSTS":
        posts = context.user_data.get("session_posts", [])
        media_type = "text"
        media_file_id = None
        text_content = text
        
        if update.message.photo:
            media_type = "photo"
            media_file_id = update.message.photo[-1].file_id
            text_content = update.message.caption or ""
        elif update.message.video:
            media_type = "video"
            media_file_id = update.message.video.file_id
            text_content = update.message.caption or ""
        elif update.message.document:
            media_type = "document"
            media_file_id = update.message.document.file_id
            text_content = update.message.caption or ""
        
        posts.append((text_content, media_type, media_file_id))
        context.user_data["session_posts"] = posts
        
        if len(posts) >= 15:
            active = await db_get_active_channel(user_id)
            if active:
                saved = await db_save_posts(active, posts)
                await update.message.reply_text(f"✅ تم حفظ {saved} منشور")
            context.user_data.pop("state", None)
            context.user_data.pop("session_posts", None)
            await main_menu_callback(update, context)
        else:
            await update.message.reply_text(f"📥 {len(posts)}/15")
        return

async def filter_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass
