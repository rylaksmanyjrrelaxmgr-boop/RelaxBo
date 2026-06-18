#!/usr/bin/env python3
import asyncio
import sqlite3
import random
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ===================== التوكن والإعدادات =====================
TOKEN = "8232359959:AAHkrv7oHns4iteuHPJM8X-rxi5JMlyNX9I"
BOT_USERNAME = "Reelaaaxbot"

# ===================== قاعدة البيانات =====================
def init_db():
    conn = sqlite3.connect("bot_data.db")
    conn.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        auto_publish INTEGER DEFAULT 1
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        channel_id TEXT,
        channel_name TEXT
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id TEXT,
        text TEXT,
        published INTEGER DEFAULT 0
    )''')
    conn.commit()
    conn.close()

init_db()

def get_channels(user_id):
    conn = sqlite3.connect("bot_data.db")
    cur = conn.execute("SELECT channel_id, channel_name FROM channels WHERE user_id=?", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def add_channel(user_id, channel_id, channel_name):
    conn = sqlite3.connect("bot_data.db")
    conn.execute("INSERT INTO channels (user_id, channel_id, channel_name) VALUES (?, ?, ?)", (user_id, channel_id, channel_name))
    conn.commit()
    conn.close()

def delete_channel(user_id, channel_id):
    conn = sqlite3.connect("bot_data.db")
    conn.execute("DELETE FROM channels WHERE user_id=? AND channel_id=?", (user_id, channel_id))
    conn.execute("DELETE FROM posts WHERE channel_id=?", (channel_id,))
    conn.commit()
    conn.close()

def add_post(channel_id, text):
    conn = sqlite3.connect("bot_data.db")
    conn.execute("INSERT INTO posts (channel_id, text) VALUES (?, ?)", (channel_id, text))
    conn.commit()
    conn.close()

def get_posts(channel_id):
    conn = sqlite3.connect("bot_data.db")
    cur = conn.execute("SELECT id, text FROM posts WHERE channel_id=? AND published=0", (channel_id,))
    posts = cur.fetchall()
    conn.close()
    return posts

def mark_published(post_id):
    conn = sqlite3.connect("bot_data.db")
    conn.execute("UPDATE posts SET published=1 WHERE id=?", (post_id,))
    conn.commit()
    conn.close()

def reset_posts(channel_id):
    conn = sqlite3.connect("bot_data.db")
    conn.execute("UPDATE posts SET published=0 WHERE channel_id=?", (channel_id,))
    conn.commit()
    conn.close()

# ===================== واجهة المستخدم (أزرار عربية) =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect("bot_data.db")
    conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()
    
    keyboard = [
        [InlineKeyboardButton("➕ إضافة قناة", callback_data="add_ch")],
        [InlineKeyboardButton("📡 قنواتي", callback_data="my_ch")],
        [InlineKeyboardButton("📥 إضافة منشور", callback_data="add_post")],
        [InlineKeyboardButton("📤 نشر الآن", callback_data="publish_now")],
        [InlineKeyboardButton("♻️ إعادة تدوير", callback_data="recycle")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")],
        [InlineKeyboardButton("❓ المساعدة", callback_data="help")],
    ]
    await update.message.reply_text("🌿 أهلاً بك في البوت العربي\nجميع الأزرار بالعربية ✅", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    
    if data == "add_ch":
        context.user_data['state'] = "wait_ch"
        await query.edit_message_text("📢 أرسل معرف القناة (مثال: @username أو -1001234567890)")
    
    elif data == "my_ch":
        channels = get_channels(user_id)
        if not channels:
            await query.edit_message_text("📭 لا توجد قنوات مسجلة")
            return
        text = "📡 **قنواتك:**\n"
        keyboard = []
        for ch_id, ch_name in channels:
            display = ch_name if ch_name != ch_id else ch_id
            text += f"• {display}\n"
            keyboard.append([InlineKeyboardButton(f"🗑️ حذف {display}", callback_data=f"del_ch:{ch_id}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    
    elif data.startswith("del_ch:"):
        ch_id = data.split(":")[1]
        delete_channel(user_id, ch_id)
        await query.edit_message_text(f"✅ تم حذف القناة {ch_id}")
        await button_handler(update, context)  # Refresh list
    
    elif data == "add_post":
        channels = get_channels(user_id)
        if not channels:
            await query.edit_message_text("⚠️ أضف قناة أولاً")
            return
        # Store channels in context for selection
        context.user_data['pending_channels'] = channels
        keyboard = []
        for ch_id, ch_name in channels:
            display = ch_name if ch_name != ch_id else ch_id
            keyboard.append([InlineKeyboardButton(f"📢 {display}", callback_data=f"select_ch_post:{ch_id}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
        await query.edit_message_text("📝 اختر القناة التي تريد إضافة المنشور لها:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("select_ch_post:"):
        ch_id = data.split(":")[1]
        context.user_data['temp_channel_id'] = ch_id
        context.user_data['state'] = "wait_post"
        await query.edit_message_text("📝 أرسل نص المنشور:")
    
    elif data == "publish_now":
        channels = get_channels(user_id)
        if not channels:
            await query.edit_message_text("⚠️ أضف قناة أولاً")
            return
        await query.edit_message_text("🚀 جاري النشر على جميع القنوات...")
        for ch_id, ch_name in channels:
            posts = get_posts(ch_id)
            for pid, txt in posts:
                try:
                    await context.bot.send_message(ch_id, txt)
                    mark_published(pid)
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"خطأ في النشر: {e}")
        await query.edit_message_text("✅ تم نشر جميع المنشورات")
    
    elif data == "recycle":
        channels = get_channels(user_id)
        if not channels:
            await query.edit_message_text("⚠️ أضف قناة أولاً")
            return
        for ch_id, ch_name in channels:
            reset_posts(ch_id)
        await query.edit_message_text("♻️ تم إعادة تعيين جميع المنشورات (ستنشر من جديد)")
    
    elif data == "settings":
        conn = sqlite3.connect("bot_data.db")
        cur = conn.execute("SELECT auto_publish FROM users WHERE user_id=?", (user_id,))
        auto = cur.fetchone()[0]
        conn.close()
        status = "🟢 مفعل" if auto else "🔴 معطل"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{status} النشر التلقائي", callback_data="toggle_auto")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")]
        ])
        await query.edit_message_text("⚙️ **الإعدادات**\n\nيمكنك تفعيل أو تعطيل النشر التلقائي", reply_markup=kb, parse_mode="Markdown")
    
    elif data == "toggle_auto":
        conn = sqlite3.connect("bot_data.db")
        conn.execute("UPDATE users SET auto_publish = NOT auto_publish WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        await query.edit_message_text("✅ تم تغيير حالة النشر التلقائي")
        await button_handler(update, context)
    
    elif data == "help":
        text = """📖 **المساعدة**
━━━━━━━━━━━━━━━━━━━━━━
➕ إضافة قناة - أضف قناة جديدة
📡 قنواتي - عرض وإدارة قنواتك
📥 إضافة منشور - أضف منشوراً جديداً
📤 نشر الآن - انشر جميع المنشورات فوراً
♻️ إعادة تدوير - إعادة تعيين المنشورات لتنشر من جديد
⚙️ الإعدادات - إعدادات البوت

⏱️ النشر التلقائي يعمل كل 12 دقيقة"""
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")]]))
    
    elif data == "main_menu":
        await start(update, context)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    state = context.user_data.get('state')
    
    if state == "wait_ch":
        add_channel(user_id, text, text)
        await update.message.reply_text(f"✅ تم إضافة القناة {text}")
        context.user_data['state'] = None
        await start(update, context)
    
    elif state == "wait_post":
        ch_id = context.user_data.get('temp_channel_id')
        if ch_id:
            add_post(ch_id, text)
            await update.message.reply_text(f"✅ تم حفظ المنشور للقناة {ch_id}")
        else:
            await update.message.reply_text("⚠️ حدث خطأ، حاول مرة أخرى")
        context.user_data['state'] = None
        await start(update, context)
    
    else:
        await start(update, context)

# ===================== حلقة النشر التلقائي =====================
async def auto_publish_loop(app):
    await asyncio.sleep(10)
    print("🔄 بدء حلقة النشر التلقائي")
    while True:
        try:
            conn = sqlite3.connect("bot_data.db")
            cur = conn.execute("SELECT user_id FROM users WHERE auto_publish=1")
            users = cur.fetchall()
            conn.close()
            
            for (uid,) in users:
                channels = get_channels(uid)
                for ch_id, ch_name in channels:
                    posts = get_posts(ch_id)
                    for pid, txt in posts:
                        try:
                            await app.bot.send_message(ch_id, txt)
                            mark_published(pid)
                            print(f"✅ نشر في {ch_name}")
                        except Exception as e:
                            print(f"❌ فشل النشر في {ch_name}: {e}")
                        await asyncio.sleep(3)
            await asyncio.sleep(720)  # 12 دقيقة
        except Exception as e:
            print(f"⚠️ خطأ في حلقة النشر: {e}")
            await asyncio.sleep(60)

# ===================== التشغيل =====================
async def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    asyncio.create_task(auto_publish_loop(app))
    print("🚀 البوت شغال | النشر على جميع القنوات كل 12 دقيقة")
    print("✅ جميع الأزرار بالعربية")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
