#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys, asyncio, time, re, hashlib, io, csv, shutil, logging, json
from datetime import datetime, timedelta
from pathlib import Path

# رفع إصدار المكتبات
def install(pkg):
    try: __import__(pkg.split("==")[0]); return True
    except: __import__("subprocess").check_call([sys.executable,"-m","pip","install",pkg,"--quiet"]); return True

for p in ["python-telegram-bot>=21.0","aiosqlite","python-dotenv","aiohttp","deep-translator","cryptography","watchdog"]:
    install(p)

from dotenv import load_dotenv; load_dotenv()
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, ChatPermissions, LabeledPrice
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, PreCheckoutQueryHandler
import aiosqlite
from deep_translator import GoogleTranslator
from cryptography.fernet import Fernet
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN: print("❌ BOT_TOKEN"); sys.exit(1)
OWNER = int(os.getenv("OWNER_ID","0"))
BOT_USER = os.getenv("BOT_USERNAME","bot")
BOT_NAME = os.getenv("BOT_NAME","Bot")
PORT = int(os.getenv("PORT","10000"))
RENDER_URL = os.getenv("RENDER_URL","")
DB = "data/bot.db"
Path(DB).parent.mkdir(exist_ok=True)

BANNED_WORDS_FILE = Path("banned_words.txt")
REPLIES_FILE = Path("replies.json")
GROUPS_FILE = Path("groups.json")

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
            CREATE TABLE IF NOT EXISTS user_messages(user_id INTEGER, chat_id INTEGER, message_time TEXT, PRIMARY KEY(user_id, chat_id));
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

# ---------- ملفات خارجية ----------
def read_banned_words_file():
    if BANNED_WORDS_FILE.exists():
        with open(BANNED_WORDS_FILE, 'r', encoding='utf-8') as f:
            return [line.strip().lower() for line in f if line.strip() and not line.startswith('#')]
    return []

def read_replies_file():
    if REPLIES_FILE.exists():
        with open(REPLIES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def read_groups_file():
    if GROUPS_FILE.exists():
        with open(GROUPS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

class FileWatcher(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith('banned_words.txt'):
            asyncio.create_task(reload_banned_words())
        elif event.src_path.endswith('replies.json'):
            asyncio.create_task(reload_replies())
        elif event.src_path.endswith('groups.json'):
            asyncio.create_task(reload_groups())

async def reload_banned_words():
    words = read_banned_words_file()
    for w in words:
        await db("INSERT OR IGNORE INTO banned_words(word,chat_id) VALUES(?,-1)", w)
    global _bw_cache; _bw_cache = {}
    await load_bw()
    logger.info(f"✅ {len(words)} كلمة محظورة")

async def reload_replies():
    replies = read_replies_file()
    for kw, rep in replies.items():
        await db("INSERT OR REPLACE INTO replies VALUES(?,?)", kw, rep)
    logger.info(f"✅ {len(replies)} رد")

async def reload_groups():
    groups = read_groups_file()
    count = 0
    for gid, settings in groups.items():
        if not gid.lstrip('-').isdigit(): continue
        await db("INSERT OR IGNORE INTO group_settings(chat_id) VALUES(?)", int(gid))
        for k, v in settings.items():
            await db(f"UPDATE group_settings SET {k}=? WHERE chat_id=?", v, int(gid))
        count += 1
    logger.info(f"✅ {count} مجموعة")

def start_file_watcher():
    observer = Observer()
    observer.schedule(FileWatcher(), path=".", recursive=False)
    observer.start()
    logger.info("👁️ مراقبة الملفات مفعلة")
    return observer

# ---------- دوال مساعدة ----------
async def perm(bot, cid, uid):
    if uid == OWNER: return True
    if await db1("SELECT 1 FROM owners WHERE chat_id=? AND user_id=?", cid, uid): return True
    if await db1("SELECT 1 FROM admins WHERE chat_id=? AND user_id=?", cid, uid): return True
    try:
        m = await bot.get_chat_member(cid, uid)
        if m.status in ['creator','administrator']: return True
    except: pass
    return False

async def get_target(update, context):
    if update.message.reply_to_message: return update.message.reply_to_message.from_user
    if context.args:
        try: return await context.bot.get_chat(f"@{context.args[0].replace('@','')}")
        except:
            try: return await context.bot.get_chat(int(context.args[0]))
            except: return None
    return None

def has_links(t): return bool(re.search(r'https?://\S+', t or ""))
def has_mentions(t): return bool(re.search(r'@\w+', t or ""))

_bw_cache = {}
async def load_bw():
    global _bw_cache
    r = await db("SELECT chat_id, word FROM banned_words")
    _bw_cache = {}
    for x in r: _bw_cache.setdefault(x['chat_id'], []).append(x['word'])

async def add_pts(uid, pts):
    await db("INSERT OR IGNORE INTO users(user_id) VALUES(?)", uid)
    await db("UPDATE users SET points=points+? WHERE user_id=?", pts, uid)
    row = await db1("SELECT points, level FROM users WHERE user_id=?", uid)
    if row:
        lvl = (row['points']//100)+1
        if lvl > row['level']: await db("UPDATE users SET level=? WHERE user_id=?", lvl, uid)

async def db_has_active_subscription(uid):
    sub = await db1("SELECT subscription_end FROM users WHERE user_id=?", uid)
    if sub and sub["subscription_end"]:
        try:
            end = datetime.fromisoformat(dec(sub["subscription_end"]))
            return end > datetime.now()
        except:
            return False
    return False

async def db_get_subscription_days_left(uid):
    sub = await db1("SELECT subscription_end FROM users WHERE user_id=?", uid)
    if sub and sub["subscription_end"]:
        try:
            end = datetime.fromisoformat(dec(sub["subscription_end"]))
            days = (end - datetime.now()).days
            return max(0, days)
        except:
            return 0
    return 0

# ---------- لغة ----------
user_lang = {}
def get_lang(uid): return user_lang.get(uid, "ar")

LANG_TEXTS = {
    "ar": {
        "add_ch": "➕ إضافة قناة", "chs": "📂 قنواتي", "settings": "⚙️ الإعدادات",
        "add_p": "📝 إضافة 15 منشور", "pub": "🚀 نشر واحد", "my_posts": "📋 منشوراتي",
        "recycle": "🔄 إعادة تدوير", "stats": "📊 إحصائيات", "ch_stats": "📈 إحصائيات القناة",
        "rank": "🏆 رتبتي", "schedule": "📅 جدولة منشور", "top": "⭐ أفضل 10",
        "publish_all": "📢 نشر الكل", "help": "❓ المساعدة", "lang": "🌐 اللغة",
        "trial": "🆓 تجربة مجانية", "sub": "💎 اشتراك", "support": "📩 الدعم",
        "grps": "👥 مجموعاتي", "contests": "🏆 المسابقات", "ref": "🔗 الإحالات",
        "remind": "⏰ التذكيرات", "trans": "🌐 ترجمة", "dev": "👨‍💻 المطور",
        "add_bot": "➕ أضف البوت", "reload": "🔄 تحديث", "admin": "👑 لوحة الأدمن",
        "back": "🔙 رجوع",
    },
    "en": {
        "add_ch": "➕ Add Channel", "chs": "📂 My Channels", "settings": "⚙️ Settings",
        "add_p": "📝 Add 15 Posts", "pub": "🚀 Publish One", "my_posts": "📋 My Posts",
        "recycle": "🔄 Recycle", "stats": "📊 Stats", "ch_stats": "📈 Channel Stats",
        "rank": "🏆 My Rank", "schedule": "📅 Schedule Post", "top": "⭐ Top 10",
        "publish_all": "📢 Publish All", "help": "❓ Help", "lang": "🌐 Language",
        "trial": "🆓 Free Trial", "sub": "💎 Subscribe", "support": "📩 Support",
        "grps": "👥 My Groups", "contests": "🏆 Contests", "ref": "🔗 Referrals",
        "remind": "⏰ Reminders", "trans": "🌐 Translate", "dev": "👨‍💻 Developer",
        "add_bot": "➕ Add Bot", "reload": "🔄 Reload", "admin": "👑 Admin Panel",
        "back": "🔙 Back",
    }
}

def t(uid, key):
    lang = get_lang(uid)
    return LANG_TEXTS.get(lang, LANG_TEXTS["ar"]).get(key, key)

def main_kb(uid):
    is_admin = uid == OWNER
    kb = [
        [InlineKeyboardButton(t(uid, "add_ch"), callback_data="add_ch"),
         InlineKeyboardButton(t(uid, "chs"), callback_data="chs"),
         InlineKeyboardButton(t(uid, "settings"), callback_data="settings")],
        [InlineKeyboardButton(t(uid, "add_p"), callback_data="add_p"),
         InlineKeyboardButton(t(uid, "pub"), callback_data="pub"),
         InlineKeyboardButton(t(uid, "my_posts"), callback_data="my_posts")],
        [InlineKeyboardButton(t(uid, "recycle"), callback_data="recycle"),
         InlineKeyboardButton(t(uid, "stats"), callback_data="stats"),
         InlineKeyboardButton(t(uid, "ch_stats"), callback_data="ch_stats")],
        [InlineKeyboardButton(t(uid, "rank"), callback_data="rank"),
         InlineKeyboardButton(t(uid, "schedule"), callback_data="schedule"),
         InlineKeyboardButton(t(uid, "top"), callback_data="top")],
        [InlineKeyboardButton(t(uid, "publish_all"), callback_data="publish_all"),
         InlineKeyboardButton(t(uid, "help"), callback_data="help"),
         InlineKeyboardButton(t(uid, "lang"), callback_data="lang")],
        [InlineKeyboardButton(t(uid, "trial"), callback_data="trial"),
         InlineKeyboardButton(t(uid, "sub"), callback_data="sub"),
         InlineKeyboardButton(t(uid, "support"), callback_data="support")],
        [InlineKeyboardButton(t(uid, "grps"), callback_data="grps"),
         InlineKeyboardButton(t(uid, "contests"), callback_data="contests"),
         InlineKeyboardButton(t(uid, "ref"), callback_data="ref")],
        [InlineKeyboardButton(t(uid, "remind"), callback_data="remind"),
         InlineKeyboardButton(t(uid, "trans"), callback_data="trans"),
         InlineKeyboardButton(t(uid, "dev"), callback_data="dev")],
        [InlineKeyboardButton(t(uid, "add_bot"), url=f"https://t.me/{BOT_USER}?startgroup"),
         InlineKeyboardButton(t(uid, "reload"), callback_data="reload_files")],
    ]
    if is_admin:
        kb.append([InlineKeyboardButton(t(uid, "admin"), callback_data="admin")])
    return InlineKeyboardMarkup(kb)

# الأوامر الأساسية (لن نكرر كل شيء لكنها موجودة)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await db("INSERT OR IGNORE INTO users(user_id) VALUES(?)", u.id)
    row = await db1("SELECT language FROM users WHERE user_id=?", u.id)
    user_lang[u.id] = row['language'] if row else "ar"
    if context.args and context.args[0].startswith("ref_"):
        code = context.args[0][4:]
        ref = await db1("SELECT user_id FROM users WHERE referral_code=?", code)
        if ref and ref['user_id'] != u.id:
            await db("INSERT OR IGNORE INTO referrals VALUES(?,?)", ref['user_id'], u.id)
            await db("INSERT OR IGNORE INTO rewards(user_id) VALUES(?)", ref['user_id'])
            await db("UPDATE rewards SET total=total+5 WHERE user_id=?", ref['user_id'])
    await update.message.reply_text(f"🌿 {BOT_NAME}\nاختر:", reply_markup=main_kb(u.id))

# اشتراك بالنجوم
STARS_PACKAGES = [
    ("sub_1_5", "1 يوم", 1, 5),
    ("sub_2_9", "2 يوم", 2, 9),
    ("sub_30_50", "30 يوم", 30, 50),
    ("sub_90_120", "90 يوم", 90, 120),
]

async def subscribe_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    if await db_has_active_subscription(uid):
        days = await db_get_subscription_days_left(uid)
        await query.edit_message_text(f"✅ اشتراكك مفعل، متبقي {days} يوم", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t(uid,"back"), callback_data="back")]]))
    else:
        kb = []
        for payload, name, d, s in STARS_PACKAGES:
            kb.append([InlineKeyboardButton(f"⭐ {name} - {s} نجوم", callback_data=f"buy:{d}:{s}")])
        kb.append([InlineKeyboardButton(t(uid,"back"), callback_data="back")])
        await query.edit_message_text("💎 اختر الباقة:", reply_markup=InlineKeyboardMarkup(kb))

async def send_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    data = query.data.split(":")
    days = int(data[1])
    stars = int(data[2])
    
    title = f"اشتراك {days} يوم"
    description = f"باقة {days} يوم مقابل {stars} نجمة"
    payload = f"sub_{days}_{stars}"
    currency = "XTR"
    prices = [LabeledPrice(f"{days} يوم", stars)]
    
    await context.bot.send_invoice(
        chat_id=uid,
        title=title,
        description=description,
        payload=payload,
        currency=currency,
        prices=prices,
        start_parameter="subscribe"
    )
    await query.edit_message_text("📩 تم إرسال فاتورة الدفع، يرجى إتمام الشراء.")

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    _, days, stars = payload.split("_")
    days = int(days)
    uid = update.effective_user.id
    await db("UPDATE users SET subscription_end=? WHERE user_id=?", enc((datetime.now()+timedelta(days=days)).isoformat()), uid)
    await update.message.reply_text(f"✅ تم شراء {days} يوم بنجاح! شكراً لاشتراكك.")

# باقي الأوامر والكولباكس كما هي من الإصدار السابق (لن نكررها هنا لكنها موجودة في الرفع الكامل)
# ... 

# المهام الخلفية
async def auto_pub(app):
    await asyncio.sleep(10)
    while True:
        try:
            interval = (await db1("SELECT value FROM settings WHERE key='publish_interval'"))['value']
            interval = int(interval)
        except: interval = 720
        try:
            channels = await db("SELECT id, user_id, channel_id FROM channels WHERE auto_publish=1")
            for ch in channels:
                p = await db1("SELECT * FROM posts WHERE channel_db_id=? AND published=0 ORDER BY id LIMIT 1", ch['id'])
                if not p: continue
                try:
                    if p['media_type']=="photo": await app.bot.send_photo(ch['channel_id'], p['media_file_id'], caption=p['text'])
                    elif p['media_type']=="video": await app.bot.send_video(ch['channel_id'], p['media_file_id'], caption=p['text'])
                    else: await app.bot.send_message(ch['channel_id'], p['text'])
                    await db("UPDATE posts SET published=1 WHERE id=?", p['id'])
                    await add_pts(ch['user_id'], 1)
                except: pass
                await asyncio.sleep(2)
        except: pass
        await asyncio.sleep(interval)

async def reminder_loop(app):
    await asyncio.sleep(30)
    while True:
        try:
            rows = await db("SELECT * FROM reminders WHERE sub=1")
            for r in rows:
                r = dict(r)
                sub = await db1("SELECT subscription_end FROM users WHERE user_id=?", r['user_id'])
                if sub and sub['subscription_end']:
                    try:
                        end_str = dec(sub['subscription_end'])
                        if end_str:
                            days = (datetime.fromisoformat(end_str) - datetime.now()).days
                            if 0 < days <= r.get('days_before',3):
                                try: await app.bot.send_message(r['user_id'], f"⏰ اشتراكك ينتهي خلال {days} يوم")
                                except: pass
                    except: pass
        except: pass
        await asyncio.sleep(3600)

async def self_ping():
    if not RENDER_URL: return
    await asyncio.sleep(60)
    while True:
        try:
            async with __import__('aiohttp').ClientSession() as session:
                async with session.get(f"{RENDER_URL}/health", timeout=10) as resp:
                    if resp.status == 200: logger.info("🫀 نبض ناجح")
        except: pass
        await asyncio.sleep(300)

async def health(request):
    from aiohttp import web
    return web.json_response({"status":"ok","bot":BOT_NAME})

async def start_web():
    from aiohttp import web
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info(f"✅ Web on port {PORT}")

async def main():
    await get_db()
    await load_bw()
    if BANNED_WORDS_FILE.exists(): await reload_banned_words()
    if REPLIES_FILE.exists(): await reload_replies()
    if GROUPS_FILE.exists(): await reload_groups()
    
    observer = start_file_watcher()
    
    app = Application.builder().token(TOKEN).build()
    
    # معالجات الأوامر (موجودة بالكامل في الرفع)
    app.add_handler(CommandHandler("start", start))
    # ... بقية الأوامر
    
    # معالجات الدفع
    app.add_handler(CallbackQueryHandler(subscribe_menu, pattern="^sub$"))
    app.add_handler(CallbackQueryHandler(send_invoice, pattern="^buy:"))
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    # معالجات أخرى
    app.add_handler(CallbackQueryHandler(btn))  # يحتوي كل الازرار
    
    # مهام خلفية
    asyncio.create_task(auto_pub(app))
    asyncio.create_task(reminder_loop(app))
    asyncio.create_task(start_web())
    asyncio.create_task(self_ping())
    
    logger.info(f"✅ {BOT_NAME} - دفع حقيقي بالنجوم")
    try:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        while True:
            await asyncio.sleep(3600)
    finally:
        await app.stop()
        await app.shutdown()
        observer.stop()
        observer.join()

if __name__ == "__main__":
    asyncio.run(main())
