#!/usr/bin/env python3
import os, sys, asyncio, time, re, hashlib, io, csv, shutil, logging, json
from datetime import datetime, timedelta
from pathlib import Path

def install(pkg):
    try: __import__(pkg.split("==")[0]); return True
    except: __import__("subprocess").check_call([sys.executable,"-m","pip","install",pkg,"--quiet"]); return True

for p in ["python-telegram-bot>=21.0","aiosqlite","python-dotenv","aiohttp","deep-translator","cryptography","watchdog"]:
    install(p)

from dotenv import load_dotenv; load_dotenv()
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import aiosqlite
from cryptography.fernet import Fernet

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN: print("❌ BOT_TOKEN"); sys.exit(1)
OWNER = int(os.getenv("OWNER_ID","0"))
BOT_USER = os.getenv("BOT_USERNAME","bot")
BOT_NAME = os.getenv("BOT_NAME","Bot")
PORT = int(os.getenv("PORT","10000"))
DB = "data/bot.db"
Path(DB).parent.mkdir(exist_ok=True)

KEY = os.getenv("ENC_KEY")
if not KEY: KEY = Fernet.generate_key().decode()
fernet = Fernet(KEY.encode())
def enc(t): return fernet.encrypt(t.encode()).decode() if t else None
def dec(t): return fernet.decrypt(t.encode()).decode() if t else None

_db = None
async def get_db():
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB)
        _db.row_factory = aiosqlite.Row
        await _db.executescript("""
            CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, banned INTEGER DEFAULT 0, language TEXT DEFAULT 'ar', points INTEGER DEFAULT 0, level INTEGER DEFAULT 1, active_channel INTEGER, referral_code TEXT, subscription_end TEXT, auto_publish INTEGER DEFAULT 1, warns INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, channel_id TEXT, channel_name TEXT, auto_publish INTEGER DEFAULT 1);
            CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY AUTOINCREMENT, channel_db_id INTEGER, text TEXT, media_type TEXT DEFAULT 'text', media_file_id TEXT, published INTEGER DEFAULT 0, scheduled_time TEXT);
            CREATE TABLE IF NOT EXISTS scheduled_tasks(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, task_type TEXT, task_data TEXT, execute_at TEXT, executed INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS groups(chat_id INTEGER PRIMARY KEY, chat_name TEXT, added_by INTEGER);
            CREATE TABLE IF NOT EXISTS owners(chat_id INTEGER, user_id INTEGER, PRIMARY KEY(chat_id, user_id));
            CREATE TABLE IF NOT EXISTS admins(chat_id INTEGER, user_id INTEGER, PRIMARY KEY(chat_id, user_id));
            CREATE TABLE IF NOT EXISTS group_settings(chat_id INTEGER PRIMARY KEY, lock_links INTEGER DEFAULT 0, lock_mentions INTEGER DEFAULT 0, slow_mode INTEGER DEFAULT 0, welcome_msg TEXT, goodbye_msg TEXT);
            CREATE TABLE IF NOT EXISTS mod_log(id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, admin_id INTEGER, target_id INTEGER, action TEXT, reason TEXT, timestamp TEXT);
            CREATE TABLE IF NOT EXISTS replies(keyword TEXT PRIMARY KEY, reply TEXT);
            CREATE TABLE IF NOT EXISTS banned_words(id INTEGER PRIMARY KEY AUTOINCREMENT, word TEXT, chat_id INTEGER DEFAULT -1, UNIQUE(word, chat_id));
            CREATE TABLE IF NOT EXISTS contests(id INTEGER PRIMARY KEY AUTOINCREMENT, creator_id INTEGER, title TEXT, prize TEXT, end_date TEXT, status TEXT DEFAULT 'active');
            CREATE TABLE IF NOT EXISTS contest_parts(contest_id INTEGER, user_id INTEGER, PRIMARY KEY(contest_id, user_id));
            CREATE TABLE IF NOT EXISTS contest_winners(contest_id INTEGER, winner_id INTEGER, PRIMARY KEY(contest_id, winner_id));
            CREATE TABLE IF NOT EXISTS referrals(ref_id INTEGER, new_id INTEGER, PRIMARY KEY(ref_id, new_id));
            CREATE TABLE IF NOT EXISTS rewards(user_id INTEGER PRIMARY KEY, total INTEGER DEFAULT 0, claimed INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS reminders(user_id INTEGER PRIMARY KEY, sub INTEGER DEFAULT 1, daily INTEGER DEFAULT 0, weekly INTEGER DEFAULT 1, days_before INTEGER DEFAULT 3);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, message TEXT, num INTEGER, status TEXT DEFAULT 'pending');
            INSERT OR IGNORE INTO settings VALUES('publish_interval','720');
            INSERT OR IGNORE INTO settings VALUES('last_ticket','0');
        """)
        await _db.commit()
    return _db

async def db(query, *p):
    c = await get_db()
    r = await c.execute(query, p)
    await c.commit()
    if "SELECT" in query.upper()[:10]: return await r.fetchall()
    return None

async def db1(query, *p):
    c = await get_db()
    r = await c.execute(query, p)
    return await r.fetchone()

async def perm(bot, cid, uid):
    if uid == OWNER: return True
    if await db1("SELECT 1 FROM owners WHERE chat_id=? AND user_id=?", cid, uid): return True
    if await db1("SELECT 1 FROM admins WHERE chat_id=? AND user_id=?", cid, uid): return True
    try:
        m = await bot.get_chat_member(cid, uid)
        if m.status in ['creator','administrator']: return True
    except: pass
    return False

def has_links(t): return bool(re.search(r'https?://\S+', t or ""))
def has_mentions(t): return bool(re.search(r'@\w+', t or ""))

_bw_cache = {}
async def load_bw():
    global _bw_cache
    r = await db("SELECT chat_id, word FROM banned_words")
    _bw_cache = {}
    for x in r: _bw_cache.setdefault(x['chat_id'], []).append(x['word'])

user_lang = {}
def get_lang(uid): return user_lang.get(uid, "ar")

def main_kb(uid):
    is_admin = uid == OWNER
    kb = [
        [InlineKeyboardButton("➕ إضافة قناة", callback_data="add_ch"),
         InlineKeyboardButton("📂 قنواتي", callback_data="chs"),
         InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")],
        [InlineKeyboardButton("👥 مجموعاتي", callback_data="grps"),
         InlineKeyboardButton("❓ المساعدة", callback_data="help"),
         InlineKeyboardButton("🌐 اللغة", callback_data="lang")],
        [InlineKeyboardButton("➕ أضف البوت", url=f"https://t.me/{BOT_USER}?startgroup")],
    ]
    if is_admin:
        kb.append([InlineKeyboardButton("👑 لوحة الأدمن", callback_data="admin")])
    return InlineKeyboardMarkup(kb)

# الأوامر
async def auto_reg(update: Update, context):
    if not update.message or not update.message.new_chat_members: return
    for m in update.message.new_chat_members:
        if m.id == context.bot.id:
            cid, uid = update.effective_chat.id, update.effective_user.id
            await db("INSERT OR IGNORE INTO groups VALUES(?,?,?)", cid, update.effective_chat.title, uid)
            if not await db1("SELECT 1 FROM owners WHERE chat_id=?", cid):
                await db("INSERT INTO owners VALUES(?,?)", cid, uid)
                try: await context.bot.send_message(uid, f"✅ مالك مخفي\n📌 {update.effective_chat.title}")
                except: pass

async def start(update: Update, context):
    u = update.effective_user
    await db("INSERT OR IGNORE INTO users(user_id) VALUES(?)", u.id)
    row = await db1("SELECT language FROM users WHERE user_id=?", u.id)
    user_lang[u.id] = row['language'] if row else "ar"
    await update.message.reply_text(f"🌿 {BOT_NAME}\nاختر:", reply_markup=main_kb(u.id))

async def help_cmd(update, context): await update.message.reply_text("/start /help /claim /check")
async def ping_cmd(update, context):
    start = time.time(); msg = await update.message.reply_text("🫀...")
    end = time.time(); ping_time = round((end - start) * 1000)
    try: await db1("SELECT 1"); db_status = "✅"
    except: db_status = "❌"
    await msg.edit_text(f"🫀 بنق: {ping_time}ms\n🗄️ القاعدة: {db_status}")

async def check_cmd(update, context):
    uid = update.effective_user.id
    gs = await db("SELECT COUNT(*) as c FROM groups")
    my_o = await db("SELECT COUNT(*) as c FROM owners WHERE user_id=?", uid)
    my_a = await db("SELECT COUNT(*) as c FROM admins WHERE user_id=?", uid)
    await update.message.reply_text(f"📊 المجموعات: {gs[0]['c']}\n👑 مالك: {my_o[0]['c']}\n🛡️ مشرف: {my_a[0]['c']}")

async def claim(update, context):
    u,c = update.effective_user.id, update.effective_chat.id
    if update.effective_chat.type not in ['group','supergroup']: return
    await db("INSERT OR IGNORE INTO groups VALUES(?,?,?)", c, update.effective_chat.title, u)
    await db("INSERT OR IGNORE INTO owners VALUES(?,?)", c, u)
    await update.message.reply_text("✅ مالك مخفي")

async def lock_links(update, context):
    u,c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    await db("INSERT OR IGNORE INTO group_settings(chat_id) VALUES(?)", c)
    await db("UPDATE group_settings SET lock_links=1 WHERE chat_id=?", c)
    await update.message.reply_text("✅ حظر الروابط مفعل")

async def unlock_links(update, context):
    u,c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    await db("UPDATE group_settings SET lock_links=0 WHERE chat_id=?", c)
    await update.message.reply_text("✅ تم إلغاء حظر الروابط")

# الكولباكس
async def btn(update: Update, context):
    q = update.callback_query
    await q.answer()
    uid, d = update.effective_user.id, q.data
    
    if d == "back":
        await q.edit_message_text(f"🌿 {BOT_NAME}\nاختر:", reply_markup=main_kb(uid))
    elif d == "grps":
        all_groups = await db("""
            SELECT DISTINCT g.chat_id, g.chat_name FROM groups g
            LEFT JOIN owners o ON g.chat_id = o.chat_id AND o.user_id = ?
            LEFT JOIN admins a ON g.chat_id = a.chat_id AND a.user_id = ?
            WHERE g.added_by = ? OR o.user_id IS NOT NULL OR a.user_id IS NOT NULL
        """, uid, uid, uid)
        if not all_groups:
            return await q.edit_message_text("📭 لا تملك صلاحيات في أي مجموعة")
        kb = []
        for g in all_groups:
            cid = g['chat_id']
            name = str(g['chat_name'] or f"مجموعة {cid}").strip()[:50]
            kb.append([InlineKeyboardButton(f"📌 {name}", url=f"https://t.me/c/{str(cid).replace('-100','')}")])
        kb.append([InlineKeyboardButton("🔙", callback_data="back")])
        await q.edit_message_text("اختر مجموعة:", reply_markup=InlineKeyboardMarkup(kb))
    elif d == "help":
        await help_cmd(update, context)
    elif d == "lang":
        kb = [[InlineKeyboardButton("العربية", callback_data="lang_ar"), InlineKeyboardButton("English", callback_data="lang_en")]]
        await q.edit_message_text("🌐 اختر اللغة / Choose language:", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("lang_"):
        lang = d.split("_")[1]
        await db("UPDATE users SET language=? WHERE user_id=?", lang, uid)
        user_lang[uid] = lang
        await q.edit_message_text("✅ تم تغيير اللغة" if lang=="ar" else "✅ Language changed", reply_markup=main_kb(uid))
    elif d == "admin":
        if uid != OWNER: return await q.answer("🔒")
        await q.edit_message_text("👑 لوحة الأدمن", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🫀 فحص النبض", callback_data="ping_status")],
            [InlineKeyboardButton("🔙", callback_data="back")]
        ]))
    elif d == "ping_status":
        start = time.time(); await q.answer()
        ping_time = round((time.time() - start) * 1000)
        try: await db1("SELECT 1"); db_status = "✅"
        except: db_status = "❌"
        await q.edit_message_text(f"🫀 نبض\n⏱️ {ping_time}ms\n🗄️ {db_status}\n🕐 {datetime.now().strftime('%H:%M:%S')}")
    else:
        await q.answer("❓")

async def main():
    await get_db()
    await load_bw()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, auto_reg), group=1)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("ping", ping_cmd))
    app.add_handler(CommandHandler("check", check_cmd))
    app.add_handler(CommandHandler("claim", claim))
    app.add_handler(CommandHandler("lock_links", lock_links))
    app.add_handler(CommandHandler("unlock_links", unlock_links))
    app.add_handler(CallbackQueryHandler(btn))
    
    await app.bot.set_my_commands([
        BotCommand("start","بدء"), BotCommand("help","مساعدة"), BotCommand("ping","فحص"),
        BotCommand("check","تشخيص"), BotCommand("claim","تسجيل مجموعة"),
        BotCommand("lock_links","قفل الروابط"), BotCommand("unlock_links","فتح الروابط")
    ])
    
    logger.info("✅ البوت يعمل")
    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
