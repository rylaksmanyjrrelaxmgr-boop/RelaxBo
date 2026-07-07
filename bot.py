#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys, asyncio, time, re, hashlib, io, csv, shutil, logging, json
from datetime import datetime, timedelta
from pathlib import Path

def install(pkg):
    try: __import__(pkg); return True
    except: __import__("subprocess").check_call([sys.executable,"-m","pip","install",pkg,"--quiet"]); return True

for p in ["python-telegram-bot","aiosqlite","python-dotenv","aiohttp","deep-translator","cryptography","watchdog"]:
    install(p)

from dotenv import load_dotenv; load_dotenv()
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import aiosqlite
from deep_translator import GoogleTranslator
from cryptography.fernet import Fernet
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== CONFIG ====================
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

# ==================== DATABASE ====================
_db = None
async def get_db():
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB)
        _db.row_factory = aiosqlite.Row
        await _db.executescript("""
            CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, banned INTEGER DEFAULT 0, language TEXT DEFAULT 'ar', points INTEGER DEFAULT 0, level INTEGER DEFAULT 1, active_channel INTEGER, referral_code TEXT, subscription_end TEXT, auto_publish INTEGER DEFAULT 1, warns INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, channel_id TEXT, channel_name TEXT);
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

# ==================== FILE READERS ====================
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

# ==================== FILE WATCHER ====================
class FileWatcher(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith('banned_words.txt'):
            logger.info("🔄 تحديث: banned_words.txt")
            asyncio.create_task(reload_banned_words())
        elif event.src_path.endswith('replies.json'):
            logger.info("🔄 تحديث: replies.json")
            asyncio.create_task(reload_replies())
        elif event.src_path.endswith('groups.json'):
            logger.info("🔄 تحديث: groups.json")
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
        if not gid.lstrip('-').isdigit():
            continue
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

# ==================== HELPERS ====================
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
    for x in r:
        _bw_cache.setdefault(x['chat_id'], []).append(x['word'])

async def add_pts(uid, pts):
    await db("INSERT OR IGNORE INTO users(user_id) VALUES(?)", uid)
    await db("UPDATE users SET points=points+? WHERE user_id=?", pts, uid)
    row = await db1("SELECT points, level FROM users WHERE user_id=?", uid)
    if row:
        lvl = (row['points']//100)+1
        if lvl > row['level']: await db("UPDATE users SET level=? WHERE user_id=?", lvl, uid)

# ==================== KEYBOARDS ====================
def main_kb(uid):
    is_admin = uid == OWNER
    kb = [
        [InlineKeyboardButton("➕ إضافة قناة", callback_data="add_ch"),
         InlineKeyboardButton("📂 قنواتي", callback_data="chs"),
         InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")],
        [InlineKeyboardButton("📝 إضافة 15 منشور", callback_data="add_p"),
         InlineKeyboardButton("🚀 نشر واحد", callback_data="pub"),
         InlineKeyboardButton("📋 منشوراتي", callback_data="my_posts")],
        [InlineKeyboardButton("🔄 إعادة تدوير", callback_data="recycle"),
         InlineKeyboardButton("📊 إحصائيات", callback_data="stats"),
         InlineKeyboardButton("📈 إحصائيات القناة", callback_data="ch_stats")],
        [InlineKeyboardButton("🏆 رتبتي", callback_data="rank"),
         InlineKeyboardButton("📅 جدولة منشور", callback_data="schedule"),
         InlineKeyboardButton("⭐ أفضل 10", callback_data="top")],
        [InlineKeyboardButton("📢 نشر الكل", callback_data="publish_all"),
         InlineKeyboardButton("❓ المساعدة", callback_data="help"),
         InlineKeyboardButton("🌐 اللغة", callback_data="lang")],
        [InlineKeyboardButton("🆓 تجربة مجانية", callback_data="trial"),
         InlineKeyboardButton("💎 اشتراك", callback_data="sub"),
         InlineKeyboardButton("📩 الدعم", callback_data="support")],
        [InlineKeyboardButton("👥 مجموعاتي", callback_data="grps"),
         InlineKeyboardButton("🏆 المسابقات", callback_data="contests"),
         InlineKeyboardButton("🔗 الإحالات", callback_data="ref")],
        [InlineKeyboardButton("⏰ التذكيرات", callback_data="remind"),
         InlineKeyboardButton("🌐 ترجمة", callback_data="trans"),
         InlineKeyboardButton("👨‍💻 المطور", callback_data="dev")],
        [InlineKeyboardButton("➕ أضف البوت", url=f"https://t.me/{BOT_USER}?startgroup"),
         InlineKeyboardButton("🔄 تحديث", callback_data="reload_files")],
    ]
    if is_admin:
        kb.append([InlineKeyboardButton("👑 لوحة الأدمن", callback_data="admin")])
    return InlineKeyboardMarkup(kb)

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 المستخدمين", callback_data="adm_users"),
         InlineKeyboardButton("🚫 المحظورين", callback_data="adm_banned")],
        [InlineKeyboardButton("📡 القنوات", callback_data="adm_channels"),
         InlineKeyboardButton("📊 المجموعات", callback_data="adm_groups")],
        [InlineKeyboardButton("💬 الردود", callback_data="adm_replies"),
         InlineKeyboardButton("📋 التذاكر", callback_data="adm_tickets")],
        [InlineKeyboardButton("➕ إضافة رد", callback_data="adm_addreply"),
         InlineKeyboardButton("🗑️ حذف رد", callback_data="adm_delreply")],
        [InlineKeyboardButton("🏆 إنشاء مسابقة", callback_data="adm_contest"),
         InlineKeyboardButton("🏅 إعلان فائز", callback_data="declare_winner")],
        [InlineKeyboardButton("📨 إذاعة", callback_data="adm_broadcast"),
         InlineKeyboardButton("📋 الفائزين", callback_data="winners")],
        [InlineKeyboardButton("💾 نسخ احتياطي", callback_data="adm_backup"),
         InlineKeyboardButton("📥 تصدير", callback_data="adm_export")],
        [InlineKeyboardButton("🫀 فحص النبض", callback_data="ping_status"),
         InlineKeyboardButton("🔄 تحديث", callback_data="reload_files")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")],
    ])
        [InlineKeyboardButton("👥 عرض المستخدمين", callback_data="adm_users")],
        [InlineKeyboardButton("🚫 عرض المحظورين", callback_data="adm_banned")],
        [InlineKeyboardButton("📡 عرض القنوات", callback_data="adm_channels")],
        [InlineKeyboardButton("📊 عرض المجموعات", callback_data="adm_groups")],
        [InlineKeyboardButton("💬 الردود التلقائية", callback_data="adm_replies")],
        [InlineKeyboardButton("📋 تذاكر الدعم", callback_data="adm_tickets")],
        [InlineKeyboardButton("➕ إضافة رد", callback_data="adm_addreply")],
        [InlineKeyboardButton("🗑️ حذف رد", callback_data="adm_delreply")],
        [InlineKeyboardButton("🏆 إنشاء مسابقة", callback_data="adm_contest")],
        [InlineKeyboardButton("🏅 إعلان فائز", callback_data="declare_winner")],
        [InlineKeyboardButton("📨 إذاعة عامة", callback_data="adm_broadcast")],
        [InlineKeyboardButton("📋 عرض الفائزين", callback_data="winners")],
        [InlineKeyboardButton("💾 نسخ احتياطي", callback_data="adm_backup")],
        [InlineKeyboardButton("📥 تصدير بيانات", callback_data="adm_export")],
        [InlineKeyboardButton("🫀 فحص النبض", callback_data="ping_status")],
        [InlineKeyboardButton("🔄 تحديث الملفات", callback_data="reload_files")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")],
    ])
        [InlineKeyboardButton("👥 مستخدمين", callback_data="adm_users"), InlineKeyboardButton("🚫 محظورين", callback_data="adm_banned")],
        [InlineKeyboardButton("📡 قنوات", callback_data="adm_channels"), InlineKeyboardButton("📊 مجموعات", callback_data="adm_groups")],
        [InlineKeyboardButton("💬 ردود", callback_data="adm_replies"), InlineKeyboardButton("📋 تذاكر", callback_data="adm_tickets")],
        [InlineKeyboardButton("➕ رد", callback_data="adm_addreply"), InlineKeyboardButton("🗑️ حذف رد", callback_data="adm_delreply")],
        [InlineKeyboardButton("🏆 مسابقة", callback_data="adm_contest"), InlineKeyboardButton("🏅 فائز", callback_data="declare_winner")],
        [InlineKeyboardButton("📨 إذاعة", callback_data="adm_broadcast"), InlineKeyboardButton("📋 فائزين", callback_data="winners")],
        [InlineKeyboardButton("💾 نسخ", callback_data="adm_backup"), InlineKeyboardButton("📥 تصدير", callback_data="adm_export")],
        [InlineKeyboardButton("🫀 نبض", callback_data="ping_status"), InlineKeyboardButton("🔄 تحديث", callback_data="reload_files")],
        [InlineKeyboardButton("🔙", callback_data="back")],
    ])

# ==================== HANDLERS ====================
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

async def on_join(update: Update, context):
    if not update.message or not update.message.new_chat_members: return
    cid = update.effective_chat.id
    s = await db1("SELECT welcome_msg FROM group_settings WHERE chat_id=?", cid)
    if s and s['welcome_msg']:
        for m in update.message.new_chat_members:
            if not m.is_bot:
                try: await update.message.reply_text(s['welcome_msg'].replace('{user}', m.first_name).replace('{chat}', update.effective_chat.title))
                except: pass

async def on_leave(update: Update, context):
    if not update.message or not update.message.left_chat_member: return
    cid = update.effective_chat.id
    s = await db1("SELECT goodbye_msg FROM group_settings WHERE chat_id=?", cid)
    if s and s['goodbye_msg']:
        m = update.message.left_chat_member
        if not m.is_bot:
            try: await update.message.reply_text(s['goodbye_msg'].replace('{user}', m.first_name).replace('{chat}', update.effective_chat.title))
            except: pass

async def start(update: Update, context):
    u = update.effective_user
    await db("INSERT OR IGNORE INTO users(user_id) VALUES(?)", u.id)
    if context.args and context.args[0].startswith("ref_"):
        code = context.args[0][4:]
        ref = await db1("SELECT user_id FROM users WHERE referral_code=?", code)
        if ref and ref['user_id'] != u.id:
            await db("INSERT OR IGNORE INTO referrals VALUES(?,?)", ref['user_id'], u.id)
            await db("INSERT OR IGNORE INTO rewards(user_id) VALUES(?)", ref['user_id'])
            await db("UPDATE rewards SET total=total+5 WHERE user_id=?", ref['user_id'])
    await update.message.reply_text(f"🌿 {BOT_NAME}\nاختر:", reply_markup=main_kb(u.id))

async def help_cmd(update: Update, context):
    await update.message.reply_text("""🛡️ **أوامر البوت:**
/start - القائمة /help - مساعدة /ping - فحص /reload - تحديث
/claim - مالك /addowner - +مالك /addadmin - +مشرف
/remove - إزالة /list - عرض
/ban - حظر /unban - فك /mute - كتم /unmute - فك
/kick - طرد /pin - تثبيت /unpin - إلغاء
/promote - ترقية /demote - تنزيل /purge - حذف
/info - معلومات /report - إبلاغ /warn - تحذير
/transfer - نقل /broadcast - إذاعة
/lock_links - حظر روابط /unlock_links - فك
/lock_mentions - حظر @ /unlock_mentions - فك
/slowmode - بطيء /welcome - ترحيب /goodbye - وداع""")

async def claim(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if update.effective_chat.type not in ['group','supergroup']: return
    await db("INSERT OR IGNORE INTO owners VALUES(?,?)", c, u)
    await update.message.reply_text("✅ مالك مخفي")

async def addowner(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    t = await get_target(update, context)
    if not t: return await update.message.reply_text("/addowner @user")
    await db("INSERT OR IGNORE INTO owners VALUES(?,?)", c, t.id)
    await update.message.reply_text(f"✅ {t.first_name}")

async def addadmin(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    t = await get_target(update, context)
    if not t: return await update.message.reply_text("/addadmin @user")
    await db("INSERT OR IGNORE INTO admins VALUES(?,?)", c, t.id)
    await update.message.reply_text(f"✅ {t.first_name}")

async def remove(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    t = await get_target(update, context)
    if not t: return await update.message.reply_text("/remove @user")
    await db("DELETE FROM owners WHERE chat_id=? AND user_id=?", c, t.id)
    await db("DELETE FROM admins WHERE chat_id=? AND user_id=?", c, t.id)
    await update.message.reply_text(f"✅ {t.first_name}")

async def lst(update: Update, context):
    c = update.effective_chat.id
    o = await db("SELECT user_id FROM owners WHERE chat_id=?", c)
    a = await db("SELECT user_id FROM admins WHERE chat_id=?", c)
    m = "👑:\n"
    for r in o:
        try: m += f"• {(await context.bot.get_chat(r[0])).first_name}\n"
        except: m += f"• {r[0]}\n"
    m += "\n🛡️:\n"
    for r in a:
        try: m += f"• {(await context.bot.get_chat(r[0])).first_name}\n"
        except: m += f"• {r[0]}\n"
    await update.message.reply_text(m or "فارغ")

async def ban(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    t = await get_target(update, context)
    if not t: return await update.message.reply_text("📝 بالرد أو /ban @user")
    try:
        await context.bot.ban_chat_member(c, t.id)
        await db("INSERT INTO mod_log(chat_id,admin_id,target_id,action,reason,timestamp) VALUES(?,?,?,?,?,?)", c, u, t.id, "ban", "حظر", datetime.now().isoformat())
        await update.message.reply_text(f"✅ حظر {t.first_name}")
    except Exception as e: await update.message.reply_text(f"❌ {e}")

async def unban(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    if not context.args: return await update.message.reply_text("/unban @user")
    try:
        t = await context.bot.get_chat(f"@{context.args[0].replace('@','')}")
        await context.bot.unban_chat_member(c, t.id)
        await update.message.reply_text(f"✅ فك حظر {t.first_name}")
    except: await update.message.reply_text("❌")

async def mute(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    t = await get_target(update, context)
    if not t: return await update.message.reply_text("📝 بالرد أو /mute @user")
    try:
        await context.bot.restrict_chat_member(c, t.id, ChatPermissions(can_send_messages=False))
        await db("INSERT INTO mod_log(chat_id,admin_id,target_id,action,reason,timestamp) VALUES(?,?,?,?,?,?)", c, u, t.id, "mute", "كتم", datetime.now().isoformat())
        await update.message.reply_text(f"🔇 كتم {t.first_name}")
    except Exception as e: await update.message.reply_text(f"❌ {e}")

async def unmute(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    t = await get_target(update, context)
    if not t: return await update.message.reply_text("/unmute @user")
    try:
        await context.bot.restrict_chat_member(c, t.id, ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True))
        await update.message.reply_text(f"🔊 فك كتم {t.first_name}")
    except Exception as e: await update.message.reply_text(f"❌ {e}")

async def kick(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    t = await get_target(update, context)
    if not t: return await update.message.reply_text("📝 بالرد أو /kick @user")
    try:
        await context.bot.ban_chat_member(c, t.id)
        await context.bot.unban_chat_member(c, t.id)
        await db("INSERT INTO mod_log(chat_id,admin_id,target_id,action,reason,timestamp) VALUES(?,?,?,?,?,?)", c, u, t.id, "kick", "طرد", datetime.now().isoformat())
        await update.message.reply_text(f"👢 طرد {t.first_name}")
    except Exception as e: await update.message.reply_text(f"❌ {e}")

async def pin(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    if not update.message.reply_to_message: return await update.message.reply_text("📝 بالرد")
    try:
        await context.bot.pin_chat_message(c, update.message.reply_to_message.message_id)
        await update.message.reply_text("📌 تم التثبيت")
    except Exception as e: await update.message.reply_text(f"❌ {e}")

async def unpin(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    try:
        await context.bot.unpin_chat_message(c)
        await update.message.reply_text("✅ تم إلغاء التثبيت")
    except Exception as e: await update.message.reply_text(f"❌ {e}")

async def promote(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    t = await get_target(update, context)
    if not t: return await update.message.reply_text("/promote @user")
    try:
        await context.bot.promote_chat_member(c, t.id, can_manage_chat=True, can_delete_messages=True, can_restrict_members=True, can_promote_members=True, can_change_info=True, can_invite_users=True, can_pin_messages=True)
        await update.message.reply_text(f"⭐ ترقية {t.first_name}")
    except Exception as e: await update.message.reply_text(f"❌ {e}")

async def demote(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    t = await get_target(update, context)
    if not t: return await update.message.reply_text("/demote @user")
    try:
        await context.bot.promote_chat_member(c, t.id, can_manage_chat=False, can_delete_messages=False, can_restrict_members=False, can_promote_members=False, can_change_info=False, can_invite_users=False, can_pin_messages=False)
        await update.message.reply_text(f"⬇️ تنزيل {t.first_name}")
    except Exception as e: await update.message.reply_text(f"❌ {e}")

async def purge(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    try: count = int(context.args[0]) if context.args else 10
    except: count = 10
    try:
        deleted = 0
        async for msg in context.bot.get_chat_history(c, limit=count):
            if msg.from_user.id == context.bot.id or await perm(context.bot, c, u):
                try: await msg.delete(); deleted += 1
                except: pass
        await update.message.reply_text(f"🗑️ حذف {deleted}")
    except Exception as e: await update.message.reply_text(f"❌ {e}")

async def info(update: Update, context):
    t = await get_target(update, context)
    if t:
        warns = (await db1("SELECT warns FROM users WHERE user_id=?", t.id))
        w = warns['warns'] if warns else 0
        await update.message.reply_text(f"👤 {t.first_name}\n🆔 {t.id}\n⚠️ تحذيرات: {w}/3")
    else:
        c = update.effective_chat
        await update.message.reply_text(f"📊 {c.title}\n🆔 {c.id}\n👥 النوع: {c.type}")

async def report(update: Update, context):
    if not update.message.reply_to_message: return await update.message.reply_text("📝 بالرد")
    t = update.message.reply_to_message.from_user
    c = update.effective_chat
    await db("INSERT INTO mod_log(chat_id,admin_id,target_id,action,reason,timestamp) VALUES(?,?,?,?,?,?)", c.id, update.effective_user.id, t.id, "report", "إبلاغ", datetime.now().isoformat())
    await update.message.reply_text(f"✅ تم الإبلاغ عن {t.first_name}")

async def warn(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    t = await get_target(update, context)
    if not t: return await update.message.reply_text("📝 بالرد أو /warn @user")
    await db("INSERT OR IGNORE INTO users(user_id) VALUES(?)", t.id)
    await db("UPDATE users SET warns=warns+1 WHERE user_id=?", t.id)
    warns = (await db1("SELECT warns FROM users WHERE user_id=?", t.id))['warns']
    await db("INSERT INTO mod_log(chat_id,admin_id,target_id,action,reason,timestamp) VALUES(?,?,?,?,?,?)", c, u, t.id, "warn", f"تحذير {warns}/3", datetime.now().isoformat())
    if warns >= 3:
        try: await context.bot.ban_chat_member(c, t.id)
        except: pass
        await update.message.reply_text(f"🚫 {t.first_name} محظور (3 تحذيرات)")
    else:
        await update.message.reply_text(f"⚠️ تحذير {t.first_name} ({warns}/3)")

async def transfer(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    t = await get_target(update, context)
    if not t: return await update.message.reply_text("/transfer @user")
    await db("DELETE FROM owners WHERE chat_id=?", c)
    await db("INSERT INTO owners VALUES(?,?)", c, t.id)
    await update.message.reply_text(f"👑 نقل الملكية إلى {t.first_name}")

async def broadcast(update: Update, context):
    u = update.effective_user.id
    if u != OWNER: return await update.message.reply_text("❌")
    txt = " ".join(context.args)
    if not txt: return await update.message.reply_text("/broadcast نص")
    users = await db("SELECT user_id FROM users WHERE banned=0")
    sent = 0
    for x in users:
        try: await context.bot.send_message(x['user_id'], txt); sent += 1
        except: pass
        await asyncio.sleep(0.1)
    await update.message.reply_text(f"✅ {sent}")

async def lock_links(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    await db("INSERT OR IGNORE INTO group_settings(chat_id) VALUES(?)", c)
    await db("UPDATE group_settings SET lock_links=1 WHERE chat_id=?", c)
    await update.message.reply_text("✅ حظر الروابط مفعل")

async def unlock_links(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    await db("UPDATE group_settings SET lock_links=0 WHERE chat_id=?", c)
    await update.message.reply_text("✅ تم إلغاء حظر الروابط")

async def lock_mentions(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    await db("INSERT OR IGNORE INTO group_settings(chat_id) VALUES(?)", c)
    await db("UPDATE group_settings SET lock_mentions=1 WHERE chat_id=?", c)
    await update.message.reply_text("✅ حظر الإشارات مفعل")

async def unlock_mentions(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    await db("UPDATE group_settings SET lock_mentions=0 WHERE chat_id=?", c)
    await update.message.reply_text("✅ تم إلغاء حظر الإشارات")

async def slowmode(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    try: s = int(context.args[0]) if context.args else 0
    except: return await update.message.reply_text("/slowmode 5")
    await db("INSERT OR IGNORE INTO group_settings(chat_id) VALUES(?)", c)
    await db("UPDATE group_settings SET slow_mode=? WHERE chat_id=?", s, c)
    await update.message.reply_text(f"✅ وضع بطيء: {s}ث")

async def welcome(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    msg = " ".join(context.args) if context.args else ""
    await db("INSERT OR IGNORE INTO group_settings(chat_id) VALUES(?)", c)
    await db("UPDATE group_settings SET welcome_msg=? WHERE chat_id=?", msg, c)
    await update.message.reply_text("✅ تم")

async def goodbye(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    msg = " ".join(context.args) if context.args else ""
    await db("INSERT OR IGNORE INTO group_settings(chat_id) VALUES(?)", c)
    await db("UPDATE group_settings SET goodbye_msg=? WHERE chat_id=?", msg, c)
    await update.message.reply_text("✅ تم")

async def add_banned(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    if not context.args: return await update.message.reply_text("/add_banned كلمة")
    await db("INSERT OR IGNORE INTO banned_words(word,chat_id) VALUES(?,?)", context.args[0].lower(), c)
    global _bw_cache; _bw_cache = {}
    await update.message.reply_text("✅")

async def remove_banned(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    if not context.args: return await update.message.reply_text("/remove_banned كلمة")
    await db("DELETE FROM banned_words WHERE word=? AND chat_id=?", context.args[0].lower(), c)
    global _bw_cache; _bw_cache = {}
    await update.message.reply_text("✅")

async def list_banned(update: Update, context):
    c = update.effective_chat.id
    words = await db("SELECT word FROM banned_words WHERE chat_id=? OR chat_id=-1", c)
    t = "🚫:\n" + ", ".join(w['word'] for w in words) if words else "لا يوجد"
    await update.message.reply_text(t)

async def add_reply(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    if len(context.args) < 2: return await update.message.reply_text("/add_reply كلمة رد")
    await db("INSERT OR REPLACE INTO replies VALUES(?,?)", context.args[0].lower(), " ".join(context.args[1:]))
    await update.message.reply_text("✅")

async def remove_reply(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await perm(context.bot, c, u): return await update.message.reply_text("❌")
    if not context.args: return await update.message.reply_text("/remove_reply كلمة")
    await db("DELETE FROM replies WHERE keyword=?", context.args[0].lower())
    await update.message.reply_text("✅")

async def list_replies(update: Update, context):
    r = await db("SELECT * FROM replies")
    t = "💬:\n" + "\n".join(f"• {x['keyword']} → {x['reply'][:30]}" for x in r) if r else "لا يوجد"
    await update.message.reply_text(t)

async def log_cmd(update: Update, context):
    c = update.effective_chat.id
    logs = await db("SELECT * FROM mod_log WHERE chat_id=? ORDER BY id DESC LIMIT 20", c)
    t = "📜:\n" + "\n".join(f"• {x['action']} → {x['target_id']} ({x['timestamp'][:16]})" for x in logs) if logs else "لا يوجد"
    await update.message.reply_text(t)

async def group_settings_cmd(update: Update, context):
    c = update.effective_chat.id
    s = await db1("SELECT * FROM group_settings WHERE chat_id=?", c)
    if not s: return await update.message.reply_text("لا توجد إعدادات")
    t = f"🔗:{'✅' if s['lock_links'] else '❌'} @:{'✅' if s['lock_mentions'] else '❌'} ⏱️:{s['slow_mode']}ث"
    await update.message.reply_text(t)

async def ping_cmd(update: Update, context):
    start = time.time()
    msg = await update.message.reply_text("🫀 جاري الفحص...")
    end = time.time()
    ping_time = round((end - start) * 1000, 2)
    try:
        await db1("SELECT 1")
        db_status = "✅"
    except:
        db_status = "❌"
    await msg.edit_text(f"🫀 بنق: {ping_time}ms\n🗄️ القاعدة: {db_status}")

async def reload_cmd(update: Update, context):
    if update.effective_user.id != OWNER: return await update.message.reply_text("❌")
    await reload_banned_words()
    await reload_replies()
    await reload_groups()
    await update.message.reply_text("✅ تم تحديث جميع الملفات")

# ==================== GROUP MESSAGE ====================
async def group_msg(update: Update, context):
    cid, uid = update.effective_chat.id, update.effective_user.id
    txt = update.message.text or update.message.caption or ""
    if update.effective_chat.type not in ['group','supergroup'] or update.effective_user.is_bot: return
    
    s = await db1("SELECT * FROM group_settings WHERE chat_id=?", cid)
    ll = s['lock_links'] if s else 0
    lm = s['lock_mentions'] if s else 0
    slow = s['slow_mode'] if s else 0
    
    if slow > 0:
        last = await db1("SELECT message_time FROM user_messages WHERE user_id=? AND chat_id=?", uid, cid)
        now = datetime.now()
        if last:
            lt = datetime.fromisoformat(last['message_time'])
            diff = (now - lt).total_seconds()
            if diff < slow:
                try: await update.message.delete()
                except: pass
                return
        await db("INSERT OR REPLACE INTO user_messages VALUES(?,?,?)", uid, cid, now.isoformat())
    
    if ll and has_links(txt):
        try: await update.message.delete()
        except: pass
        await db("INSERT INTO mod_log(chat_id,admin_id,target_id,action,reason,timestamp) VALUES(?,?,?,?,?,?)", cid, context.bot.id, uid, "auto_delete", "رابط", datetime.now().isoformat())
        return
    if lm and has_mentions(txt):
        try: await update.message.delete()
        except: pass
        await db("INSERT INTO mod_log(chat_id,admin_id,target_id,action,reason,timestamp) VALUES(?,?,?,?,?,?)", cid, context.bot.id, uid, "auto_delete", "إشارة", datetime.now().isoformat())
        return
    
    await load_bw()
    words = _bw_cache.get(cid,[]) + _bw_cache.get(-1,[])
    for w in words:
        if w in txt.lower():
            try: await update.message.delete()
            except: pass
            return
    
    r = await db1("SELECT reply FROM replies WHERE keyword=?", txt.lower())
    if r:
        await update.message.reply_text(r['reply'])
        return
    reps = {"مرحباً":"أهلاً 🤍","السلام عليكم":"وعليكم السلام 🌹","شكراً":"العفو","كيف حالك":"الحمد لله بخير 🙏"}
    for k,v in reps.items():
        if k in txt.lower(): await update.message.reply_text(v); break

# ==================== CALLBACKS ====================
async def btn(update: Update, context):
    q = update.callback_query
    await q.answer()
    uid, d = update.effective_user.id, q.data
    
    if d == "back": await start(update, context)
    elif d == "reload_files":
        if uid != OWNER: return await q.answer("🔒")
        await reload_banned_words()
        await reload_replies()
        await reload_groups()
        await q.edit_message_text("✅ تم تحديث جميع الملفات")
    elif d == "chs":
        chs = await db("SELECT * FROM channels WHERE user_id=?", uid)
        if not chs: return await q.edit_message_text("📭")
        kb = []
        for c in chs:
            kb.append([InlineKeyboardButton(f"📢 {c['channel_name'] or c['channel_id']}", callback_data=f"sel_ch:{c['id']}")])
            kb.append([InlineKeyboardButton("🗑️ حذف", callback_data=f"del_ch:{c['id']}")])
        kb.append([InlineKeyboardButton("➕ قناة", callback_data="add_ch")])
        kb.append([InlineKeyboardButton("🔙", callback_data="back")])
        await q.edit_message_text("📡 قنواتي", reply_markup=InlineKeyboardMarkup(kb))
    elif d == "add_ch":
        context.user_data["s"] = "ADD_CH"
        await q.edit_message_text("📡 أرسل @channel")
    elif d.startswith("sel_ch:"):
        ch_id = int(d.split(":")[1])
        await db("UPDATE users SET active_channel=? WHERE user_id=?", ch_id, uid)
        await q.edit_message_text("✅ تم التفعيل", reply_markup=main_kb(uid))
    elif d.startswith("del_ch:"):
        ch_id = int(d.split(":")[1])
        await db("DELETE FROM channels WHERE id=? AND user_id=?", ch_id, uid)
        await db("DELETE FROM posts WHERE channel_db_id=?", ch_id)
        await q.edit_message_text("✅ تم الحذف", reply_markup=main_kb(uid))
    elif d == "add_p":
        ch = await db1("SELECT id FROM channels WHERE user_id=? LIMIT 1", uid)
        if not ch: return await q.edit_message_text("⚠️ لا توجد قناة")
        context.user_data["s"] = "ADD_POSTS"; context.user_data["posts"] = []
        await q.edit_message_text("📥 أرسل 15 منشور\n/cancel للإلغاء")
    elif d == "pub":
        ch = await db1("SELECT id,channel_id FROM channels WHERE user_id=? AND active_channel=id LIMIT 1", uid)
        if not ch: return await q.edit_message_text("⚠️ لا توجد قناة نشطة")
        p = await db1("SELECT * FROM posts WHERE channel_db_id=? AND published=0 ORDER BY id LIMIT 1", ch['id'])
        if not p: return await q.edit_message_text("📭 لا توجد منشورات")
        try:
            if p['media_type']=="photo": await context.bot.send_photo(ch['channel_id'], p['media_file_id'], caption=p['text'])
            elif p['media_type']=="video": await context.bot.send_video(ch['channel_id'], p['media_file_id'], caption=p['text'])
            else: await context.bot.send_message(ch['channel_id'], p['text'])
            await db("UPDATE posts SET published=1 WHERE id=?", p['id'])
            await add_pts(uid, 5)
            await q.edit_message_text("✅ تم النشر")
        except Exception as e: await q.edit_message_text(f"❌ {e}")
    elif d == "my_posts":
        ch = await db1("SELECT id FROM channels WHERE user_id=? AND active_channel=id LIMIT 1", uid)
        if not ch: return await q.edit_message_text("⚠️")
        posts = await db("SELECT * FROM posts WHERE channel_db_id=? AND published=0 ORDER BY id LIMIT 15", ch['id'])
        if not posts: return await q.edit_message_text("📭")
        txt = "📋 منشوراتي:\n"
        kb = []
        for p in posts:
            txt += f"• {p['text'][:30] if p['text'] else '🖼️'}...\n"
            kb.append([InlineKeyboardButton(f"🗑️ حذف #{p['id']}", callback_data=f"del_post:{p['id']}")])
        kb.append([InlineKeyboardButton("🗑️ حذف الكل", callback_data="del_all_posts")])
        kb.append([InlineKeyboardButton("🔙", callback_data="back")])
        await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("del_post:"):
        pid = int(d.split(":")[1])
        await db("DELETE FROM posts WHERE id=?", pid)
        await q.edit_message_text("✅ تم الحذف")
    elif d == "del_all_posts":
        ch = await db1("SELECT id FROM channels WHERE user_id=? AND active_channel=id LIMIT 1", uid)
        if ch:
            await db("DELETE FROM posts WHERE channel_db_id=?", ch['id'])
            await q.edit_message_text("✅ تم حذف الكل")
    elif d == "recycle":
        ch = await db1("SELECT id FROM channels WHERE user_id=? AND active_channel=id LIMIT 1", uid)
        if ch:
            await db("UPDATE posts SET published=0 WHERE channel_db_id=?", ch['id'])
            await q.edit_message_text("♻️ تم إعادة التدوير")
    elif d == "publish_all":
        ch = await db1("SELECT id,channel_id FROM channels WHERE user_id=? AND active_channel=id LIMIT 1", uid)
        if not ch: return await q.edit_message_text("⚠️")
        posts = await db("SELECT * FROM posts WHERE channel_db_id=? AND published=0", ch['id'])
        if not posts: return await q.edit_message_text("📭")
        count = 0
        for p in posts:
            try:
                if p['media_type']=="photo": await context.bot.send_photo(ch['channel_id'], p['media_file_id'], caption=p['text'])
                elif p['media_type']=="video": await context.bot.send_video(ch['channel_id'], p['media_file_id'], caption=p['text'])
                else: await context.bot.send_message(ch['channel_id'], p['text'])
                await db("UPDATE posts SET published=1 WHERE id=?", p['id'])
                count += 1
                await asyncio.sleep(1)
            except: pass
        await q.edit_message_text(f"✅ تم نشر {count}")
    elif d == "stats":
        chs = await db("SELECT COUNT(*) as c FROM channels WHERE user_id=?", uid)
        p = await db("SELECT COUNT(*) as c FROM posts WHERE channel_db_id IN (SELECT id FROM channels WHERE user_id=?)", uid)
        await q.edit_message_text(f"📊 قنوات: {chs[0]['c']}\n📝 منشورات: {p[0]['c']}")
    elif d == "all_stats":
        chs = await db("SELECT id, channel_name FROM channels WHERE user_id=?", uid)
        if not chs: return await q.edit_message_text("📭")
        txt = "📈 ملخص:\n"
        for c in chs:
            unpub = await db1("SELECT COUNT(*) as c FROM posts WHERE channel_db_id=? AND published=0", c['id'])
            txt += f"• {c['channel_name']}: {unpub['c']} غير منشور\n"
        await q.edit_message_text(txt)
    elif d == "ch_stats":
        ch = await db1("SELECT id,channel_name FROM channels WHERE user_id=? AND active_channel=id LIMIT 1", uid)
        if not ch: return await q.edit_message_text("⚠️")
        total = await db1("SELECT COUNT(*) as c FROM posts WHERE channel_db_id=?", ch['id'])
        pub = await db1("SELECT COUNT(*) as c FROM posts WHERE channel_db_id=? AND published=1", ch['id'])
        unpub = await db1("SELECT COUNT(*) as c FROM posts WHERE channel_db_id=? AND published=0", ch['id'])
        await q.edit_message_text(f"📊 {ch['channel_name']}\n📝 الكل: {total['c']}\n✅ منشور: {pub['c']}\n⏳ غير منشور: {unpub['c']}")
    elif d == "grps":
        g = await db("SELECT * FROM groups WHERE added_by=?", uid)
        t = "👥:\n" + "\n".join(f"• {x['chat_name']}" for x in g) if g else "📭"
        await q.edit_message_text(t)
    elif d == "contests":
        c = await db("SELECT * FROM contests WHERE status='active' AND end_date > ?", datetime.now().isoformat())
        if not c: return await q.edit_message_text("📭 لا توجد مسابقات")
        kb = [[InlineKeyboardButton(f"📌 {x['title']} - {x['prize']}", callback_data=f"jc:{x['id']}")] for x in c]
        kb.append([InlineKeyboardButton("🏆 الفائزين", callback_data="winners")])
        kb.append([InlineKeyboardButton("🔙", callback_data="back")])
        await q.edit_message_text("🏆 مسابقات", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("jc:"):
        await db("INSERT OR IGNORE INTO contest_parts VALUES(?,?)", int(d.split(":")[1]), uid)
        await q.edit_message_text("✅ تم الاشتراك")
        await add_pts(uid, 5)
    elif d == "winners":
        w = await db("SELECT c.title, cw.winner_id FROM contest_winners cw JOIN contests c ON cw.contest_id=c.id ORDER BY cw.rowid DESC LIMIT 10")
        if not w: return await q.edit_message_text("📭")
        txt = "🏆:\n"
        for x in w:
            try:
                u = await context.bot.get_chat(x['winner_id'])
                txt += f"• {x['title']} → {u.first_name}\n"
            except: txt += f"• {x['title']} → {x['winner_id']}\n"
        await q.edit_message_text(txt)
    elif d == "declare_winner":
        context.user_data["s"] = "WINNER"
        await q.edit_message_text("📝 أرسل: contest_id winner_id")
    elif d == "ref":
        code = hashlib.md5(f"{uid}{time.time()}".encode()).hexdigest()[:8]
        await db("UPDATE users SET referral_code=? WHERE user_id=?", code, uid)
        rw = await db1("SELECT total, claimed FROM rewards WHERE user_id=?", uid)
        td = rw['total'] if rw else 0; cd = rw['claimed'] if rw else 0
        kb = [
            [InlineKeyboardButton("📋 نسخ", callback_data="copy_ref")],
            [InlineKeyboardButton("🎁 صرف", callback_data="claim_reward")],
            [InlineKeyboardButton("👥 المحالين", callback_data="ref_list")],
            [InlineKeyboardButton("🔙", callback_data="back")]
        ]
        await q.edit_message_text(f"🔗 `https://t.me/{BOT_USER}?start=ref_{code}`\n👥 {td//5}\n🎁 {td-cd}", reply_markup=InlineKeyboardMarkup(kb), parse_mode="MarkdownV2")
    elif d == "copy_ref":
        code = (await db1("SELECT referral_code FROM users WHERE user_id=?", uid))['referral_code']
        if code: await q.answer(f"https://t.me/{BOT_USER}?start=ref_{code}", show_alert=True)
    elif d == "claim_reward":
        rw = await db1("SELECT total, claimed FROM rewards WHERE user_id=?", uid)
        if rw and rw['total'] > rw['claimed']:
            avail = rw['total'] - rw['claimed']
            await db("UPDATE rewards SET claimed=claimed+? WHERE user_id=?", avail, uid)
            await q.edit_message_text(f"✅ تم صرف {avail} يوم")
        else: await q.answer("❌ لا توجد مكافآت")
    elif d == "ref_list":
        refs = await db("SELECT new_id FROM referrals WHERE ref_id=?", uid)
        txt = "👥:\n" + "\n".join(f"• {x['new_id']}" for x in refs) if refs else "لا يوجد"
        await q.edit_message_text(txt)
    elif d == "remind":
        r = await db1("SELECT * FROM reminders WHERE user_id=?", uid)
        if not r: await db("INSERT INTO reminders(user_id) VALUES(?)", uid); r = await db1("SELECT * FROM reminders WHERE user_id=?", uid)
        r = dict(r)
        kb = [
            [InlineKeyboardButton(f"🔔 اشتراك: {'✅' if r['sub'] else '❌'}", callback_data="tog_sub")],
            [InlineKeyboardButton(f"📊 يومي: {'✅' if r['daily'] else '❌'}", callback_data="tog_daily")],
            [InlineKeyboardButton(f"📈 أسبوعي: {'✅' if r['weekly'] else '❌'}", callback_data="tog_weekly")],
            [InlineKeyboardButton("🔙", callback_data="back")]
        ]
        await q.edit_message_text("⏰ تذكيرات", reply_markup=InlineKeyboardMarkup(kb))
    elif d in ["tog_sub","tog_daily","tog_weekly"]:
        col = {'tog_sub':'sub','tog_daily':'daily','tog_weekly':'weekly'}[d]
        r = await db1(f"SELECT {col} FROM reminders WHERE user_id=?", uid)
        if r: await db(f"UPDATE reminders SET {col}=? WHERE user_id=?", 0 if r[col] else 1, uid)
        await q.answer("✅")
    elif d == "trans": context.user_data["tr"] = True; await q.edit_message_text("🌐 أرسل نص")
    elif d == "rank":
        r = await db1("SELECT points, level FROM users WHERE user_id=?", uid)
        await q.edit_message_text(f"⭐ Lv{r['level']} | {r['points']} نقطة" if r else "0")
    elif d == "top":
        t = await db("SELECT user_id, points, level FROM users ORDER BY points DESC LIMIT 10")
        txt = "🏆:\n" + "\n".join(f"{i}. {x['user_id']} Lv{x['level']}" for i,x in enumerate(t,1))
        await q.edit_message_text(txt or "لا")
    elif d == "trial":
        await db("UPDATE users SET subscription_end=? WHERE user_id=?", enc((datetime.now()+timedelta(days=30)).isoformat()), uid)
        await q.edit_message_text("🎁 30 يوم")
    elif d == "sub":
        kb = [[InlineKeyboardButton("⭐ 1 يوم", callback_data="buy:1"), InlineKeyboardButton("⭐ 30 يوم", callback_data="buy:30")], [InlineKeyboardButton("🔙", callback_data="back")]]
        await q.edit_message_text("💎", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("buy:"):
        days = int(d.split(":")[1])
        await db("UPDATE users SET subscription_end=? WHERE user_id=?", enc((datetime.now()+timedelta(days=days)).isoformat()), uid)
        await q.edit_message_text(f"✅ {days} يوم")
    elif d == "schedule":
        context.user_data["s"] = "SCHEDULE"
        await q.edit_message_text("📝 أرسل: YYYY-MM-DD HH:MM النص")
    elif d == "support":
        context.user_data["support"] = True
        await q.edit_message_text("📝 اكتب رسالتك")
    elif d == "dev": await q.edit_message_text("👨‍💻 @RelaxMgr")
    elif d == "help": await q.edit_message_text("/help للمساعدة الكاملة")
    elif d == "lang":
        kb = [[InlineKeyboardButton("العربية", callback_data="lang_ar"), InlineKeyboardButton("English", callback_data="lang_en")]]
        await q.edit_message_text("🌐", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("lang_"):
        await db("UPDATE users SET language=? WHERE user_id=?", d.split("_")[1], uid)
        await q.edit_message_text("✅", reply_markup=main_kb(uid))
    elif d == "admin":
        if uid != OWNER: return await q.answer("🔒")
        await q.edit_message_text("👑", reply_markup=admin_kb())
    elif d == "ping_status":
        start = time.time()
        await q.answer()
        ping_time = round((time.time() - start) * 1000, 2)
        try: await db1("SELECT 1"); db_status = "✅"
        except: db_status = "❌"
        await q.edit_message_text(f"🫀 نبض\n⏱️ {ping_time}ms\n🗄️ {db_status}\n🕐 {datetime.now().strftime('%H:%M:%S')}")
    elif d == "adm_users":
        u = await db("SELECT user_id, banned FROM users LIMIT 50")
        t = "👥:\n" + "\n".join(f"{'🚫' if x['banned'] else '✅'} {x['user_id']}" for x in u)
        await q.edit_message_text(t or "لا", reply_markup=admin_kb())
    elif d == "adm_banned":
        u = await db("SELECT user_id FROM users WHERE banned=1 LIMIT 50")
        t = "🚫:\n" + "\n".join(f"• {x['user_id']}" for x in u)
        await q.edit_message_text(t or "لا", reply_markup=admin_kb())
    elif d == "adm_channels":
        c = await db("SELECT channel_name FROM channels LIMIT 50")
        t = "📡:\n" + "\n".join(f"• {x['channel_name']}" for x in c)
        await q.edit_message_text(t or "لا", reply_markup=admin_kb())
    elif d == "adm_groups":
        g = await db("SELECT chat_name FROM groups LIMIT 50")
        t = "📊:\n" + "\n".join(f"• {x['chat_name']}" for x in g)
        await q.edit_message_text(t or "لا", reply_markup=admin_kb())
    elif d == "adm_replies":
        r = await db("SELECT * FROM replies LIMIT 30")
        t = "💬:\n" + "\n".join(f"• {x['keyword']} → {x['reply'][:30]}" for x in r)
        await q.edit_message_text(t or "لا", reply_markup=admin_kb())
    elif d == "adm_tickets":
        tic = await db("SELECT * FROM tickets ORDER BY num DESC LIMIT 10")
        t = "📋:\n" + "\n".join(f"#{x['num']} {x['username']}" for x in tic)
        await q.edit_message_text(t or "لا", reply_markup=admin_kb())
    elif d == "adm_addreply":
        context.user_data["s"] = "ADD_REPLY_KW"
        await q.edit_message_text("📝 أرسل الكلمة:")
    elif d == "adm_delreply":
        context.user_data["s"] = "DEL_REPLY"
        await q.edit_message_text("🗑️ أرسل الكلمة:")
    elif d == "adm_broadcast":
        context.user_data["s"] = "BROADCAST"
        await q.edit_message_text("📨 أرسل النص:")
    elif d == "adm_contest":
        context.user_data["s"] = "CONTEST_TITLE"
        await q.edit_message_text("📝 عنوان المسابقة:")
    elif d == "adm_backup":
        shutil.copy2(DB, f"data/backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
        await q.edit_message_text("✅")
    elif d == "adm_export":
        tables = ["users","channels","groups","posts","tickets"]
        kb = [[InlineKeyboardButton(t, callback_data=f"exp:{t}")] for t in tables]
        kb.append([InlineKeyboardButton("🔙", callback_data="admin")])
        await q.edit_message_text("📥", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("exp:"):
        table = d.split(":")[1]
        rows = await db(f"SELECT * FROM {table}")
        if rows:
            output = io.StringIO()
            w = csv.writer(output)
            w.writerow([k for k in dict(rows[0]).keys()])
            for r in rows: w.writerow([v for v in dict(r).values()])
            f = io.BytesIO(output.getvalue().encode())
            f.name = f"{table}.csv"
            await context.bot.send_document(uid, f)
            await q.edit_message_text("✅")
        else: await q.edit_message_text("❌")

# ==================== PRIVATE MESSAGE ====================
async def msg(update: Update, context):
    uid, txt = update.effective_user.id, update.message.text or ""
    s = context.user_data.get("s")
    
    if context.user_data.get("support"):
        num = (await db1("SELECT value FROM settings WHERE key='last_ticket'"))['value']
        await db("INSERT INTO tickets(user_id,username,message,num) VALUES(?,?,?,?)", uid, update.effective_user.full_name or str(uid), txt, int(num)+1)
        await db("UPDATE settings SET value=? WHERE key='last_ticket'", str(int(num)+1))
        await update.message.reply_text(f"✅ تذكرة #{int(num)+1}")
        context.user_data.pop("support", None)
        return
    
    if context.user_data.get("tr"):
        try:
            tr = GoogleTranslator(source='auto', target='ar').translate(txt)
            await update.message.reply_text(f"🌐 {tr}")
        except: await update.message.reply_text("❌")
        context.user_data.pop("tr", None)
        return
    
    if txt == "/cancel": context.user_data.clear(); return await update.message.reply_text("❌")
    
    if s == "ADD_CH":
        if not txt.startswith("@") and not txt.startswith("-100"): return
        await db("INSERT INTO channels(user_id,channel_id,channel_name) VALUES(?,?,?)", uid, txt.strip(), txt.strip())
        await db("UPDATE users SET active_channel=? WHERE user_id=?", (await db1("SELECT id FROM channels WHERE user_id=? ORDER BY id DESC LIMIT 1", uid))['id'], uid)
        await update.message.reply_text("✅", reply_markup=main_kb(uid))
        context.user_data.pop("s")
    elif s == "ADD_POSTS":
        posts = context.user_data.get("posts", [])
        mt, mf, tc = "text", None, txt
        if update.message.photo: mt, mf, tc = "photo", update.message.photo[-1].file_id, update.message.caption or ""
        elif update.message.video: mt, mf, tc = "video", update.message.video.file_id, update.message.caption or ""
        posts.append((tc, mt, mf))
        context.user_data["posts"] = posts
        if len(posts) >= 15:
            ch = await db1("SELECT id FROM channels WHERE user_id=? AND active_channel=id LIMIT 1", uid)
            if ch:
                for tx, mt, mf in posts:
                    await db("INSERT INTO posts(channel_db_id,text,media_type,media_file_id) VALUES(?,?,?,?)", ch['id'], tx, mt, mf)
            context.user_data.clear()
            await update.message.reply_text("✅", reply_markup=main_kb(uid))
        else: await update.message.reply_text(f"📥 {len(posts)}/15")
    elif s == "ADD_REPLY_KW":
        context.user_data["kw"] = txt.strip().lower()
        context.user_data["s"] = "ADD_REPLY_TXT"
        await update.message.reply_text("📝 أرسل الرد:")
    elif s == "ADD_REPLY_TXT":
        await db("INSERT OR REPLACE INTO replies VALUES(?,?)", context.user_data.get("kw",""), txt.strip())
        context.user_data.clear()
        await update.message.reply_text("✅")
    elif s == "DEL_REPLY":
        await db("DELETE FROM replies WHERE keyword=?", txt.strip().lower())
        context.user_data.pop("s")
        await update.message.reply_text("✅")
    elif s == "BROADCAST":
        users = await db("SELECT user_id FROM users WHERE banned=0")
        sent = 0
        for u in users:
            try: await context.bot.send_message(u['user_id'], txt); sent += 1
            except: pass
            await asyncio.sleep(0.1)
        context.user_data.pop("s")
        await update.message.reply_text(f"✅ {sent}")
    elif s == "CONTEST_TITLE":
        context.user_data["ctitle"] = txt
        context.user_data["s"] = "CONTEST_PRIZE"
        await update.message.reply_text("🎁 الجائزة:")
    elif s == "CONTEST_PRIZE":
        context.user_data["cprize"] = txt
        context.user_data["s"] = "CONTEST_END"
        await update.message.reply_text("📅 تاريخ الانتهاء (YYYY-MM-DD):")
    elif s == "CONTEST_END":
        try:
            end = datetime.strptime(txt.strip(), "%Y-%m-%d")
            await db("INSERT INTO contests(creator_id,title,prize,end_date) VALUES(?,?,?,?)", uid, context.user_data.get("ctitle",""), context.user_data.get("cprize",""), end.isoformat())
            await update.message.reply_text("✅")
        except: await update.message.reply_text("❌")
        context.user_data.clear()
    elif s == "WINNER":
        parts = txt.split()
        if len(parts) == 2:
            try:
                await db("INSERT OR IGNORE INTO contest_winners VALUES(?,?)", int(parts[0]), int(parts[1]))
                await db("UPDATE contests SET status='completed' WHERE id=?", int(parts[0]))
                await update.message.reply_text("✅ تم إعلان الفائز")
            except: await update.message.reply_text("❌")
        context.user_data.pop("s")
    elif s == "SCHEDULE":
        parts = txt.split(maxsplit=2)
        if len(parts) >= 2:
            try:
                dt = datetime.strptime(f"{parts[0]} {parts[1]}", "%Y-%m-%d %H:%M")
                if dt > datetime.now():
                    await db("INSERT INTO scheduled_tasks(user_id,task_type,task_data,execute_at) VALUES(?,?,?,?)", uid, "publish", parts[2] if len(parts)>2 else "", dt.isoformat())
                    await update.message.reply_text(f"✅ جدولة: {dt}")
                else: await update.message.reply_text("❌ وقت في الماضي")
            except: await update.message.reply_text("❌ خطأ")
        context.user_data.pop("s")

# ==================== TASKS ====================
async def auto_pub(app):
    await asyncio.sleep(10)
    while True:
        try:
            interval = (await db1("SELECT value FROM settings WHERE key='publish_interval'"))['value']
            interval = int(interval)
        except: interval = 720
        try:
            users = await db("SELECT user_id, active_channel FROM users WHERE banned=0 AND auto_publish=1 AND active_channel IS NOT NULL")
            for u in users:
                if not u['active_channel']: continue
                p = await db1("SELECT * FROM posts WHERE channel_db_id=? AND published=0 ORDER BY id LIMIT 1", u['active_channel'])
                if not p: continue
                ch = await db1("SELECT channel_id FROM channels WHERE id=?", u['active_channel'])
                if not ch: continue
                try:
                    if p['media_type']=="photo": await app.bot.send_photo(ch['channel_id'], p['media_file_id'], caption=p['text'])
                    elif p['media_type']=="video": await app.bot.send_video(ch['channel_id'], p['media_file_id'], caption=p['text'])
                    else: await app.bot.send_message(ch['channel_id'], p['text'])
                    await db("UPDATE posts SET published=1 WHERE id=?", p['id'])
                    await add_pts(u['user_id'], 1)
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

async def scheduler(app):
    await asyncio.sleep(20)
    while True:
        try:
            tasks = await db("SELECT * FROM scheduled_tasks WHERE executed=0 AND execute_at <= ?", datetime.now().isoformat())
            for t in tasks:
                t = dict(t)
                if t['task_type'] == "publish":
                    ch = await db1("SELECT id,channel_id FROM channels WHERE user_id=? AND active_channel=id LIMIT 1", t['user_id'])
                    if ch:
                        try: await app.bot.send_message(ch['channel_id'], t['task_data'])
                        except: pass
                await db("UPDATE scheduled_tasks SET executed=1 WHERE id=?", t['id'])
        except: pass
        await asyncio.sleep(10)

async def self_ping():
    if not RENDER_URL:
        logger.info("⚠️ RENDER_URL غير محدد")
        return
    await asyncio.sleep(60)
    logger.info(f"🫀 نبض ذاتي كل 5 دقائق: {RENDER_URL}")
    while True:
        try:
            async with __import__('aiohttp').ClientSession() as session:
                async with session.get(f"{RENDER_URL}/health", timeout=10) as resp:
                    if resp.status == 200:
                        logger.info("🫀 نبض ناجح")
                    else:
                        logger.warning(f"🫀 نبض: {resp.status}")
        except Exception as e:
            logger.error(f"🫀 نبض خطأ: {e}")
        await asyncio.sleep(300)

# ==================== WEB ====================
async def health(request):
    from aiohttp import web
    return web.json_response({
        "status": "ok",
        "bot": BOT_NAME,
        "time": datetime.now().isoformat(),
        "owner": OWNER
    })

async def start_web():
    from aiohttp import web
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/ping", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info(f"✅ Web on port {PORT}")

# ==================== MAIN ====================
async def main():
    await get_db()
    await load_bw()
    
    if BANNED_WORDS_FILE.exists():
        await reload_banned_words()
    if REPLIES_FILE.exists():
        await reload_replies()
    if GROUPS_FILE.exists():
        await reload_groups()
    
    observer = start_file_watcher()
    
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, auto_reg), group=1)
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_join), group=2)
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_leave))
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("ping", ping_cmd))
    app.add_handler(CommandHandler("reload", reload_cmd))
    app.add_handler(CommandHandler("claim", claim))
    app.add_handler(CommandHandler("addowner", addowner))
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("list", lst))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("kick", kick))
    app.add_handler(CommandHandler("pin", pin))
    app.add_handler(CommandHandler("unpin", unpin))
    app.add_handler(CommandHandler("promote", promote))
    app.add_handler(CommandHandler("demote", demote))
    app.add_handler(CommandHandler("purge", purge))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("warn", warn))
    app.add_handler(CommandHandler("transfer", transfer))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("lock_links", lock_links))
    app.add_handler(CommandHandler("unlock_links", unlock_links))
    app.add_handler(CommandHandler("lock_mentions", lock_mentions))
    app.add_handler(CommandHandler("unlock_mentions", unlock_mentions))
    app.add_handler(CommandHandler("slowmode", slowmode))
    app.add_handler(CommandHandler("welcome", welcome))
    app.add_handler(CommandHandler("goodbye", goodbye))
    app.add_handler(CommandHandler("add_banned", add_banned))
    app.add_handler(CommandHandler("remove_banned", remove_banned))
    app.add_handler(CommandHandler("list_banned", list_banned))
    app.add_handler(CommandHandler("add_reply", add_reply))
    app.add_handler(CommandHandler("remove_reply", remove_reply))
    app.add_handler(CommandHandler("list_replies", list_replies))
    app.add_handler(CommandHandler("log", log_cmd))
    app.add_handler(CommandHandler("settings", group_settings_cmd))
    app.add_handler(CallbackQueryHandler(btn))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, group_msg))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, msg))
    
    await app.bot.set_my_commands([
        BotCommand("start","بدء"), BotCommand("help","مساعدة"), BotCommand("ping","فحص"), BotCommand("reload","تحديث"),
        BotCommand("claim","مالك"), BotCommand("addowner","+مالك"), BotCommand("addadmin","+مشرف"),
        BotCommand("remove","إزالة"), BotCommand("list","عرض"),
        BotCommand("ban","حظر"), BotCommand("unban","فك"), BotCommand("mute","كتم"), BotCommand("unmute","فك"), BotCommand("kick","طرد"),
        BotCommand("pin","تثبيت"), BotCommand("unpin","إلغاء"), BotCommand("promote","ترقية"), BotCommand("demote","تنزيل"),
        BotCommand("purge","حذف"), BotCommand("info","معلومات"), BotCommand("report","إبلاغ"), BotCommand("warn","تحذير"),
        BotCommand("transfer","نقل"), BotCommand("broadcast","إذاعة"),
        BotCommand("lock_links","حظر روابط"), BotCommand("unlock_links","فك"),
        BotCommand("lock_mentions","حظر @"), BotCommand("unlock_mentions","فك"),
        BotCommand("slowmode","بطيء"), BotCommand("welcome","ترحيب"), BotCommand("goodbye","وداع"),
        BotCommand("add_banned","+كلمة"), BotCommand("remove_banned","-كلمة"), BotCommand("list_banned","كلمات"),
        BotCommand("add_reply","+رد"), BotCommand("remove_reply","-رد"), BotCommand("list_replies","ردود"),
        BotCommand("log","سجل"), BotCommand("settings","إعدادات"),
    ])
    
    asyncio.create_task(auto_pub(app))
    asyncio.create_task(reminder_loop(app))
    asyncio.create_task(scheduler(app))
    asyncio.create_task(start_web())
    asyncio.create_task(self_ping())
    
    logger.info(f"✅ {BOT_NAME} - نظام متكامل مع ملفات خارجية وتحديث تلقائي")
    try:
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
    finally:
        observer.stop()
        observer.join()

if __name__ == "__main__":
    asyncio.run(main())
