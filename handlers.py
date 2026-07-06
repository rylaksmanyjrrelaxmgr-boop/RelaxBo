import asyncio, time, hashlib, io, csv, shutil, logging, re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import fetch, execute, encrypt, decrypt
from keyboards import main_menu, admin_keyboard
from config import OWNER_ID, BOT_USERNAME
from deep_translator import GoogleTranslator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

_requests = {}
_RATE_LIMIT = 0.3

def rate_limit(update: Update) -> bool:
    uid = update.effective_user.id
    now = time.time()
    if uid in _requests and now - _requests[uid] < _RATE_LIMIT:
        return False
    _requests[uid] = now
    return True

_user_lang = {}
TXT = {
    "ar": {"welcome": "🌿 ريلاكس مانيجر\nاختر:", "help": "/start /claim /addowner /addadmin /remove /list /contests /referral /reminders /top /language"},
    "en": {"welcome": "🌿 Relax Manager\nChoose:", "help": "/start /claim /addowner /addadmin /remove /list /contests /referral /reminders /top /language"}
}
def t(uid, k):
    return TXT.get(_user_lang.get(uid,"ar"), TXT["ar"]).get(k,k)

async def load_lang():
    for row in await fetch("SELECT user_id, language FROM users WHERE language IS NOT NULL"):
        _user_lang[row['user_id']] = row['language']

async def add_points(uid, pts):
    await execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", uid)
    await execute("UPDATE users SET points=points+? WHERE user_id=?", pts, uid)
    row = await fetch("SELECT points, level FROM users WHERE user_id=?", uid)
    if row:
        lvl = (row[0]['points'] // 100) + 1
        if lvl > row[0]['level']:
            await execute("UPDATE users SET level=? WHERE user_id=?", lvl, uid)

_perm_cache = {}
_PERM_TTL = 300

async def check_perm(bot, chat_id, user_id):
    key = f"{chat_id}_{user_id}"
    now = time.time()
    if key in _perm_cache:
        ct, cr = _perm_cache[key]
        if now - ct < _PERM_TTL:
            return cr
    res = False
    if user_id == OWNER_ID: res = True
    elif await fetch("SELECT 1 FROM owners WHERE chat_id=? AND user_id=?", chat_id, user_id): res = True
    elif await fetch("SELECT 1 FROM admins WHERE chat_id=? AND user_id=?", chat_id, user_id): res = True
    else:
        try:
            m = await bot.get_chat_member(chat_id, user_id)
            if m.status in ['creator','administrator']: res = True
        except: pass
    _perm_cache[key] = (now, res)
    return res

async def get_target(update, context):
    if update.message.reply_to_message: return update.message.reply_to_message.from_user
    if context.args:
        try: return await context.bot.get_chat(f"@{context.args[0].replace('@','')}")
        except:
            try: return await context.bot.get_chat(int(context.args[0]))
            except: return None
    return None

_banned_cache = {}

async def load_banned_cache():
    global _banned_cache
    rows = await fetch("SELECT DISTINCT chat_id, word FROM banned_words ORDER BY chat_id")
    _banned_cache = {}
    for r in rows:
        _banned_cache.setdefault(r['chat_id'], []).append(r['word'])

async def has_links(text):
    return bool(re.search(r'https?://\S+', text))

async def has_mentions(text):
    return bool(re.search(r'@\w+', text))

async def log_mod(chat_id, admin_id, target_id, action, reason=""):
    await execute("INSERT INTO moderation_log (chat_id,admin_id,target_id,action,reason,timestamp) VALUES (?,?,?,?,?,?)",
                  chat_id, admin_id, target_id, action, reason, datetime.now().isoformat())

async def auto_penalty(bot, chat_id, user_id):
    try:
        await bot.ban_chat_member(chat_id, user_id)
        await bot.unban_chat_member(chat_id, user_id)
    except: pass
    await log_mod(chat_id, bot.id, user_id, "auto_kick", "مخالفة")

async def cmd_lock_links(update: Update, context):
    if update.effective_chat.type not in ['group','supergroup']: return
    u, c = update.effective_user.id, update.effective_chat.id
    if not await check_perm(context.bot, c, u): return await update.message.reply_text("❌ غير مصرح")
    await execute("INSERT OR IGNORE INTO group_settings(chat_id) VALUES(?)", c)
    await execute("UPDATE group_settings SET lock_links=1 WHERE chat_id=?", c)
    await update.message.reply_text("✅ تم تفعيل حظر الروابط")

async def cmd_unlock_links(update: Update, context):
    if update.effective_chat.type not in ['group','supergroup']: return
    u, c = update.effective_user.id, update.effective_chat.id
    if not await check_perm(context.bot, c, u): return await update.message.reply_text("❌ غير مصرح")
    await execute("UPDATE group_settings SET lock_links=0 WHERE chat_id=?", c)
    await update.message.reply_text("✅ تم إلغاء حظر الروابط")

async def cmd_lock_mentions(update: Update, context):
    if update.effective_chat.type not in ['group','supergroup']: return
    u, c = update.effective_user.id, update.effective_chat.id
    if not await check_perm(context.bot, c, u): return await update.message.reply_text("❌ غير مصرح")
    await execute("INSERT OR IGNORE INTO group_settings(chat_id) VALUES(?)", c)
    await execute("UPDATE group_settings SET lock_mentions=1 WHERE chat_id=?", c)
    await update.message.reply_text("✅ تم تفعيل حظر الإشارات")

async def cmd_unlock_mentions(update: Update, context):
    if update.effective_chat.type not in ['group','supergroup']: return
    u, c = update.effective_user.id, update.effective_chat.id
    if not await check_perm(context.bot, c, u): return await update.message.reply_text("❌ غير مصرح")
    await execute("UPDATE group_settings SET lock_mentions=0 WHERE chat_id=?", c)
    await update.message.reply_text("✅ تم إلغاء حظر الإشارات")

async def cmd_slowmode(update: Update, context):
    if update.effective_chat.type not in ['group','supergroup']: return
    u, c = update.effective_user.id, update.effective_chat.id
    if not await check_perm(context.bot, c, u): return await update.message.reply_text("❌ غير مصرح")
    try: sec = int(context.args[0]) if context.args else 0
    except: return await update.message.reply_text("/slowmode 5")
    await execute("INSERT OR IGNORE INTO group_settings(chat_id) VALUES(?)", c)
    await execute("UPDATE group_settings SET slow_mode=? WHERE chat_id=?", sec, c)
    await update.message.reply_text(f"✅ وضع بطيء: {sec} ثانية")

async def cmd_welcome(update: Update, context):
    if update.effective_chat.type not in ['group','supergroup']: return
    u, c = update.effective_user.id, update.effective_chat.id
    if not await check_perm(context.bot, c, u): return await update.message.reply_text("❌ غير مصرح")
    msg = " ".join(context.args) if context.args else ""
    await execute("INSERT OR IGNORE INTO group_settings(chat_id) VALUES(?)", c)
    await execute("UPDATE group_settings SET welcome_msg=? WHERE chat_id=?", msg, c)
    await update.message.reply_text("✅ تم تعيين رسالة الترحيب")

async def cmd_goodbye(update: Update, context):
    if update.effective_chat.type not in ['group','supergroup']: return
    u, c = update.effective_user.id, update.effective_chat.id
    if not await check_perm(context.bot, c, u): return await update.message.reply_text("❌ غير مصرح")
    msg = " ".join(context.args) if context.args else ""
    await execute("INSERT OR IGNORE INTO group_settings(chat_id) VALUES(?)", c)
    await execute("UPDATE group_settings SET goodbye_msg=? WHERE chat_id=?", msg, c)
    await update.message.reply_text("✅ تم تعيين رسالة الوداع")

async def auto_register(update: Update, context):
    if not update.message or not update.message.new_chat_members: return
    for m in update.message.new_chat_members:
        if m.id == context.bot.id:
            if not await fetch("SELECT 1 FROM owners WHERE chat_id=?", update.effective_chat.id):
                await execute("INSERT INTO owners VALUES(?,?)", update.effective_chat.id, update.effective_user.id)
                try: await context.bot.send_message(update.effective_user.id, f"✅ مالك مخفي\n📌 {update.effective_chat.title}")
                except: pass

async def start(update: Update, context):
    if not rate_limit(update): return await update.message.reply_text("⏳ تمهل")
    u = update.effective_user
    await execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", u.id)
    if context.args and context.args[0].startswith("ref_"):
        code = context.args[0][4:]
        ref = await fetch("SELECT user_id FROM users WHERE referral_code=?", code)
        if ref and ref[0]['user_id'] != u.id:
            await execute("INSERT OR IGNORE INTO referrals VALUES(?,?)", ref[0]['user_id'], u.id)
            await execute("INSERT OR IGNORE INTO referral_rewards(user_id) VALUES(?)", ref[0]['user_id'])
            await execute("UPDATE referral_rewards SET total_days=total_days+5 WHERE user_id=?", ref[0]['user_id'])
    row = await fetch("SELECT language FROM users WHERE user_id=?", u.id)
    _user_lang[u.id] = row[0]['language'] if row else "ar"
    await update.message.reply_text(t(u.id,"welcome"), reply_markup=main_menu(u.id, u.id==OWNER_ID))

async def claim(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if update.effective_chat.type not in ['group','supergroup']: return await update.message.reply_text("⚠️ للمجموعات")
    await execute("INSERT OR IGNORE INTO owners VALUES(?,?)", c, u)
    await update.message.reply_text("✅ مالك مخفي")
    await add_points(u, 10)

async def addowner(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await check_perm(context.bot, c, u): return await update.message.reply_text("❌")
    t = await get_target(update, context)
    if not t: return await update.message.reply_text("/addowner @user")
    await execute("INSERT OR IGNORE INTO owners VALUES(?,?)", c, t.id)
    await update.message.reply_text(f"✅ {t.first_name}")

async def addadmin(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await check_perm(context.bot, c, u): return await update.message.reply_text("❌")
    t = await get_target(update, context)
    if not t: return await update.message.reply_text("/addadmin @user")
    await execute("INSERT OR IGNORE INTO admins VALUES(?,?)", c, t.id)
    await update.message.reply_text(f"✅ {t.first_name}")

async def remove(update: Update, context):
    u, c = update.effective_user.id, update.effective_chat.id
    if not await check_perm(context.bot, c, u): return await update.message.reply_text("❌")
    t = await get_target(update, context)
    if not t: return await update.message.reply_text("/remove @user")
    await execute("DELETE FROM owners WHERE chat_id=? AND user_id=?", c, t.id)
    await execute("DELETE FROM admins WHERE chat_id=? AND user_id=?", c, t.id)
    await update.message.reply_text(f"✅ {t.first_name}")

async def listall(update: Update, context):
    c = update.effective_chat.id
    o = await fetch("SELECT user_id FROM owners WHERE chat_id=?", c)
    a = await fetch("SELECT user_id FROM admins WHERE chat_id=?", c)
    m = "👑:\n"
    for r in o:
        try: m += f"• {(await context.bot.get_chat(r[0])).first_name}\n"
        except: m += f"• {r[0]}\n"
    m += "\n🛡️:\n"
    for r in a:
        try: m += f"• {(await context.bot.get_chat(r[0])).first_name}\n"
        except: m += f"• {r[0]}\n"
    await update.message.reply_text(m or "فارغ")

async def handle_groups(uid, context, q):
    groups = await fetch("SELECT DISTINCT bg.chat_id, bg.chat_name FROM bot_groups bg LEFT JOIN owners o ON bg.chat_id=o.chat_id AND o.user_id=? LEFT JOIN admins a ON bg.chat_id=a.chat_id AND a.user_id=? WHERE o.user_id IS NOT NULL OR a.user_id IS NOT NULL", uid, uid)
    txt = "👥:\n" + "\n".join(f"• {g['chat_name'] or g['chat_id']}" for g in groups) if groups else "📭"
    await q.edit_message_text(txt, reply_markup=main_menu(uid, uid==OWNER_ID))

async def handle_channels(uid, context, q):
    chs = await fetch("SELECT * FROM channels WHERE user_id=?", uid)
    if not chs: return await q.edit_message_text("📭", reply_markup=main_menu(uid, uid==OWNER_ID))
    kb = [[InlineKeyboardButton(f"📢 {c['channel_name'] or c['channel_id']}", callback_data=f"sel_ch:{c['id']}")] for c in chs]
    kb.append([InlineKeyboardButton("🔙", callback_data="back")])
    await q.edit_message_text("📡", reply_markup=InlineKeyboardMarkup(kb))

async def handle_add_channel(uid, context, q):
    context.user_data["state"] = "ADD_CH"
    await q.edit_message_text("📡 أرسل @channel")

async def handle_sel_ch(uid, context, q, data):
    await execute("UPDATE users SET active_channel=? WHERE user_id=?", int(data.split(":")[1]), uid)
    await q.edit_message_text("✅", reply_markup=main_menu(uid, uid==OWNER_ID))

async def handle_add_posts(uid, context, q):
    active = (await fetch("SELECT active_channel FROM users WHERE user_id=?", uid))
    if not active or not active[0]['active_channel']: return await q.edit_message_text("⚠️ اختر قناة")
    context.user_data["state"] = "ADD_POSTS"
    context.user_data["posts"] = []
    await q.edit_message_text("📥 أرسل 15 منشور\n/cancel")

async def handle_publish_one(uid, context, q):
    active = (await fetch("SELECT active_channel FROM users WHERE user_id=?", uid))
    if not active or not active[0]['active_channel']: return await q.edit_message_text("⚠️")
    post = await fetch("SELECT * FROM posts WHERE channel_db_id=? AND published=0 ORDER BY id LIMIT 1", active[0]['active_channel'])
    if not post: return await q.edit_message_text("📭")
    post = dict(post[0])
    ch = await fetch("SELECT channel_id FROM channels WHERE id=?", active[0]['active_channel'])
    if ch:
        try:
            if post['media_type']=="photo": await context.bot.send_photo(ch[0]['channel_id'], post['media_file_id'], caption=post['text'])
            elif post['media_type']=="video": await context.bot.send_video(ch[0]['channel_id'], post['media_file_id'], caption=post['text'])
            else: await context.bot.send_message(ch[0]['channel_id'], post['text'])
            await execute("UPDATE posts SET published=1 WHERE id=?", post['id'])
            await add_points(uid, 5)
            await q.edit_message_text("✅ تم النشر")
        except Exception as e: await q.edit_message_text(f"❌ {e}")

async def handle_settings(uid, context, q):
    auto = await fetch("SELECT auto_publish FROM users WHERE user_id=?", uid)
    auto = auto[0]['auto_publish'] if auto else 1
    await q.edit_message_text(f"⚙️ النشر: {'✅' if auto else '❌'}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄", callback_data="toggle_auto")], [InlineKeyboardButton("🔙", callback_data="back")]]))

async def handle_toggle_auto(uid, context, q):
    auto = await fetch("SELECT auto_publish FROM users WHERE user_id=?", uid)
    new = 0 if (auto and auto[0]['auto_publish']) else 1
    await execute("UPDATE users SET auto_publish=? WHERE user_id=?", new, uid)
    await q.edit_message_text(f"{'✅' if new else '❌'}")

async def handle_contests(uid, context, q):
    contests = await fetch("SELECT * FROM contests WHERE status='active' AND end_date > ?", datetime.now().isoformat())
    if not contests: return await q.edit_message_text("📭")
    kb = [[InlineKeyboardButton(f"📌 {c['title']} - {c['prize']}", callback_data=f"join_contest:{c['id']}")] for c in contests]
    kb.append([InlineKeyboardButton("🔙", callback_data="back")])
    await q.edit_message_text("🏆:", reply_markup=InlineKeyboardMarkup(kb))

async def handle_join_contest(uid, context, q, data):
    cid = int(data.split(":")[1])
    await execute("INSERT OR IGNORE INTO contest_participants VALUES(?,?)", cid, uid)
    await q.edit_message_text("✅")
    await add_points(uid, 5)

async def handle_referral(uid, context, q):
    row = await fetch("SELECT referral_code FROM users WHERE user_id=?", uid)
    code = row[0]['referral_code'] if row and row[0]['referral_code'] else None
    if not code:
        code = hashlib.md5(f"{uid}{time.time()}".encode()).hexdigest()[:8]
        await execute("UPDATE users SET referral_code=? WHERE user_id=?", code, uid)
    rw = await fetch("SELECT total_days, claimed_days FROM referral_rewards WHERE user_id=?", uid)
    td = rw[0]['total_days'] if rw else 0
    cd = rw[0]['claimed_days'] if rw else 0
    await q.edit_message_text(f"🔗 `https://t.me/{BOT_USERNAME}?start=ref_{code}`\n👥 {td//5}\n🎁 {td-cd}", parse_mode="MarkdownV2")

async def handle_reminders(uid, context, q):
    r = await fetch("SELECT * FROM reminders WHERE user_id=?", uid)
    if not r: await execute("INSERT INTO reminders(user_id) VALUES(?)", uid); r = await fetch("SELECT * FROM reminders WHERE user_id=?", uid)
    r = dict(r[0])
    await q.edit_message_text(f"⏰ اشتراك:{'✅' if r['sub_reminder'] else '❌'} يومي:{'✅' if r['daily_stats'] else '❌'} أسبوعي:{'✅' if r['weekly_report'] else '❌'}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔔 اشتراك", callback_data="tog_sub"), InlineKeyboardButton("📊 يومي", callback_data="tog_daily")], [InlineKeyboardButton("📈 أسبوعي", callback_data="tog_weekly"), InlineKeyboardButton("🔙", callback_data="back")]]))

async def handle_toggle_reminder(uid, context, q, d):
    col = {'tog_sub':'sub_reminder','tog_daily':'daily_stats','tog_weekly':'weekly_report'}[d]
    r = await fetch(f"SELECT {col} FROM reminders WHERE user_id=?", uid)
    if r: await execute(f"UPDATE reminders SET {col}=? WHERE user_id=?", 0 if r[0][col] else 1, uid)
    await q.answer("✅")

async def handle_translate_mode(uid, context, q):
    context.user_data["translate_mode"] = True
    await q.edit_message_text("🌐 أرسل النص للترجمة")

async def handle_rank(uid, context, q):
    r = await fetch("SELECT points, level FROM users WHERE user_id=?", uid)
    await q.edit_message_text(f"⭐ Lv{r[0]['level']} | {r[0]['points']} نقطة" if r else "0")

async def handle_top(uid, context, q):
    top = await fetch("SELECT user_id, points, level FROM users ORDER BY points DESC LIMIT 10")
    txt = "🏆:\n"
    for i,u in enumerate(top,1):
        try:
            chat = await context.bot.get_chat(u['user_id'])
            name = chat.first_name
        except:
            name = u['user_id']
        txt += f"{i}. {name} Lv{u['level']}\n"
    await q.edit_message_text(txt or "لا يوجد")

async def handle_admin_menu(uid, context, q):
    if uid != OWNER_ID: return await q.answer("🔒")
    await q.edit_message_text("👑", reply_markup=admin_keyboard())

async def handle_admin_actions(uid, context, q, d):
    if uid != OWNER_ID: return await q.answer("🔒")
    # commands for adm_users, adm_banned, adm_channels, adm_groups, adm_replies, adm_tickets,
    # adm_addreply, adm_delreply, adm_contest, adm_broadcast, adm_backup, adm_export
    if d == "adm_users":
        users = await fetch("SELECT user_id FROM users WHERE banned=0")
        txt = "👥:\n" + "\n".join(str(u['user_id']) for u in users[:50])
        await q.edit_message_text(txt, reply_markup=admin_keyboard())
    elif d == "adm_banned":
        banned = await fetch("SELECT user_id FROM users WHERE banned=1")
        txt = "🚫:\n" + "\n".join(str(u['user_id']) for u in banned[:50])
        await q.edit_message_text(txt, reply_markup=admin_keyboard())
    elif d == "adm_channels":
        chs = await fetch("SELECT * FROM channels")
        txt = "\n".join(f"{c['user_id']} - {c['channel_name'] or c['channel_id']}" for c in chs[:50])
        await q.edit_message_text(txt or "لا يوجد", reply_markup=admin_keyboard())
    elif d == "adm_groups":
        groups = await fetch("SELECT * FROM bot_groups")
        txt = "\n".join(f"{g['chat_name'] or g['chat_id']}" for g in groups[:50])
        await q.edit_message_text(txt or "لا يوجد", reply_markup=admin_keyboard())
    elif d == "adm_replies":
        replies = await fetch("SELECT * FROM replies")
        txt = "\n".join(f"{r['keyword']}: {r['reply'][:30]}" for r in replies[:50])
        await q.edit_message_text(txt or "لا يوجد", reply_markup=admin_keyboard())
    elif d == "adm_tickets":
        tickets = await fetch("SELECT * FROM tickets WHERE status='pending'")
        txt = "\n".join(f"{t['ticket_num']} - {t['username']}: {t['message'][:30]}" for t in tickets[:20])
        await q.edit_message_text(txt or "لا تذاكر", reply_markup=admin_keyboard())
    elif d == "adm_addreply":
        context.user_data["state"] = "ADD_REPLY_KW"
        await q.edit_message_text("📝 أرسل الكلمة المفتاحية:")
    elif d == "adm_delreply":
        context.user_data["state"] = "DEL_REPLY"
        await q.edit_message_text("🗑️ أرسل الكلمة المفتاحية للحذف:")
    elif d == "adm_contest":
        context.user_data["state"] = "CONTEST_TITLE"
        await q.edit_message_text("🏆 أرسل عنوان المسابقة:")
    elif d == "adm_broadcast":
        context.user_data["state"] = "BROADCAST"
        await q.edit_message_text("📨 أرسل الرسالة للإذاعة:")
    elif d == "adm_backup":
        # simple backup: copy db file
        shutil.copy("data/bot.db", "data/backup.db")
        await q.edit_message_text("💾 تم النسخ الاحتياطي", reply_markup=admin_keyboard())
    elif d == "adm_export":
        await q.edit_message_text("اختر الجدول:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("users", callback_data="export:users"),
             InlineKeyboardButton("channels", callback_data="export:channels")],
            [InlineKeyboardButton("posts", callback_data="export:posts"),
             InlineKeyboardButton("contests", callback_data="export:contests")],
            [InlineKeyboardButton("🔙", callback_data="admin")]
        ]))

async def handle_export(uid, context, q, d):
    if uid != OWNER_ID: return
    table = d.split(":")[1]
    rows = await fetch(f"SELECT * FROM {table}")
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

async def handle_general(uid, context, q, d):
    if d == "help": await q.edit_message_text(t(uid,"help"))
    elif d == "language":
        await q.edit_message_text("🌐:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("العربية", callback_data="lang_ar"), InlineKeyboardButton("English", callback_data="lang_en")]]))
    elif d.startswith("lang_"):
        lang = d.split("_")[1]
        await execute("UPDATE users SET language=? WHERE user_id=?", lang, uid)
        _user_lang[uid] = lang
        await q.edit_message_text("✅", reply_markup=main_menu(uid, uid==OWNER_ID))
    elif d == "trial":
        await execute("UPDATE users SET subscription_end=? WHERE user_id=?", encrypt((datetime.now()+timedelta(days=30)).isoformat()), uid)
        await q.edit_message_text("🎁 30 يوم")
    elif d == "subscribe":
        await q.edit_message_text("💎:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("1 يوم", callback_data="buy:1"), InlineKeyboardButton("30 يوم", callback_data="buy:30")], [InlineKeyboardButton("🔙", callback_data="back")]]))
    elif d.startswith("buy:"):
        days = int(d.split(":")[1])
        await execute("UPDATE users SET subscription_end=? WHERE user_id=?", encrypt((datetime.now()+timedelta(days=days)).isoformat()), uid)
        await q.edit_message_text(f"✅ {days} يوم")

async def handle_posts(uid, context, q):
    active = (await fetch("SELECT active_channel FROM users WHERE user_id=?", uid))
    if not active or not active[0]['active_channel']: return await q.edit_message_text("⚠️")
    posts = await fetch("SELECT * FROM posts WHERE channel_db_id=? AND published=0 ORDER BY id LIMIT 15", active[0]['active_channel'])
    if not posts: return await q.edit_message_text("📭")
    txt = "📋:\n" + "\n".join(f"• {p['text'][:50] if p['text'] else '🖼️'}..." for p in posts)
    await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="back")]]))

async def handle_recycle(uid, context, q):
    active = (await fetch("SELECT active_channel FROM users WHERE user_id=?", uid))
    if active and active[0]['active_channel']:
        await execute("UPDATE posts SET published=0 WHERE channel_db_id=?", active[0]['active_channel'])
        await q.edit_message_text("♻️")

async def handle_stats(uid, context, q):
    active = (await fetch("SELECT active_channel FROM users WHERE user_id=?", uid))
    if not active or not active[0]['active_channel']: return await q.edit_message_text("⚠️")
    r = await fetch("SELECT COUNT(*) as c FROM posts WHERE channel_db_id=? AND published=0", active[0]['active_channel'])
    await q.edit_message_text(f"📊 {r[0]['c'] if r else 0}")

async def handle_full_stats(uid, context, q):
    chs = await fetch("SELECT * FROM channels WHERE user_id=?", uid)
    txt = "📈:\n"
    for c in chs:
        cnt = await fetch("SELECT COUNT(*) as c FROM posts WHERE channel_db_id=? AND published=0", c['id'])
        txt += f"• {c['channel_name'] or c['channel_id']}: {cnt[0]['c']}\n"
    await q.edit_message_text(txt)

async def button_handler(update: Update, context):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    d = q.data
    if d == "back": await q.edit_message_text(t(uid,"welcome"), reply_markup=main_menu(uid, uid==OWNER_ID))
    elif d == "groups": await handle_groups(uid, context, q)
    elif d == "channels": await handle_channels(uid, context, q)
    elif d == "add_channel": await handle_add_channel(uid, context, q)
    elif d.startswith("sel_ch:"): await handle_sel_ch(uid, context, q, d)
    elif d == "add_posts": await handle_add_posts(uid, context, q)
    elif d == "publish_one": await handle_publish_one(uid, context, q)
    elif d == "posts": await handle_posts(uid, context, q)
    elif d == "recycle": await handle_recycle(uid, context, q)
    elif d == "settings": await handle_settings(uid, context, q)
    elif d == "toggle_auto": await handle_toggle_auto(uid, context, q)
    elif d == "stats": await handle_stats(uid, context, q)
    elif d == "full_stats": await handle_full_stats(uid, context, q)
    elif d == "contests": await handle_contests(uid, context, q)
    elif d.startswith("join_contest:"): await handle_join_contest(uid, context, q, d)
    elif d == "referral": await handle_referral(uid, context, q)
    elif d == "reminders": await handle_reminders(uid, context, q)
    elif d in ["tog_sub","tog_daily","tog_weekly"]: await handle_toggle_reminder(uid, context, q, d)
    elif d == "translate": await handle_translate_mode(uid, context, q)
    elif d == "rank": await handle_rank(uid, context, q)
    elif d == "top": await handle_top(uid, context, q)
    elif d == "admin": await handle_admin_menu(uid, context, q)
    elif d.startswith("adm_"): await handle_admin_actions(uid, context, q, d)
    elif d.startswith("export:"): await handle_export(uid, context, q, d)
    elif d in ["help","language","lang_ar","lang_en","trial","subscribe","buy:1","buy:30"]: await handle_general(uid, context, q, d)

async def msg_handler(update: Update, context):
    uid = update.effective_user.id
    text = update.message.text or ""
    if not rate_limit(update): return await update.message.reply_text("⏳ تمهل")
    state = context.user_data.get("state")
    if context.user_data.get("translate_mode"):
        try:
            tr = GoogleTranslator(source='auto', target='ar').translate(text)
            await update.message.reply_text(f"🌐 {tr}")
        except: await update.message.reply_text("❌")
        context.user_data.pop("translate_mode", None)
        return
    if text == "/cancel":
        context.user_data.clear()
        return await update.message.reply_text("❌", reply_markup=main_menu(uid, uid==OWNER_ID))
    if state == "ADD_CH":
        if not text.startswith("@") and not text.startswith("-100"): return await update.message.reply_text("❌")
        await execute("INSERT INTO channels(user_id,channel_id,channel_name,created_at) VALUES(?,?,?,?)", uid, text.strip(), text.strip(), datetime.now().isoformat())
        context.user_data.pop("state")
        await update.message.reply_text("✅", reply_markup=main_menu(uid, uid==OWNER_ID))
    elif state == "ADD_POSTS":
        posts = context.user_data.get("posts", [])
        mt, mf, tc = "text", None, text
        if update.message.photo: mt, mf, tc = "photo", update.message.photo[-1].file_id, update.message.caption or ""
        elif update.message.video: mt, mf, tc = "video", update.message.video.file_id, update.message.caption or ""
        posts.append((tc, mt, mf))
        context.user_data["posts"] = posts
        if len(posts) >= 15:
            active = (await fetch("SELECT active_channel FROM users WHERE user_id=?", uid))
            if active and active[0]['active_channel']:
                for tx, mt, mf in posts:
                    await execute("INSERT INTO posts(channel_db_id,text,media_type,media_file_id,created_at) VALUES(?,?,?,?,?)", active[0]['active_channel'], tx, mt, mf, datetime.now().isoformat())
            context.user_data.clear()
            await update.message.reply_text("✅", reply_markup=main_menu(uid, uid==OWNER_ID))
        else: await update.message.reply_text(f"📥 {len(posts)}/15")
    elif state == "ADD_REPLY_KW":
        context.user_data["kw"] = text.strip().lower()
        context.user_data["state"] = "ADD_REPLY_TXT"
        await update.message.reply_text("📝 أرسل الرد:")
    elif state == "ADD_REPLY_TXT":
        kw = context.user_data.get("kw","")
        await execute("INSERT OR REPLACE INTO replies VALUES(?,?)", kw, text.strip())
        context.user_data.clear()
        await update.message.reply_text("✅")
    elif state == "DEL_REPLY":
        await execute("DELETE FROM replies WHERE keyword=?", text.strip().lower())
        context.user_data.pop("state")
        await update.message.reply_text("✅")
    elif state == "BROADCAST":
        users = await fetch("SELECT user_id FROM users WHERE banned=0")
        sent = 0
        for u in users:
            try: await context.bot.send_message(u['user_id'], text); sent += 1
            except: pass
            await asyncio.sleep(0.1)
        context.user_data.pop("state")
        await update.message.reply_text(f"✅ {sent}")
    elif state == "CONTEST_TITLE":
        context.user_data["ctitle"] = text
        context.user_data["state"] = "CONTEST_PRIZE"
        await update.message.reply_text("🎁 الجائزة:")
    elif state == "CONTEST_PRIZE":
        context.user_data["cprize"] = text
        context.user_data["state"] = "CONTEST_END"
        await update.message.reply_text("📅 تاريخ الانتهاء (YYYY-MM-DD):")
    elif state == "CONTEST_END":
        try:
            end = datetime.strptime(text.strip(), "%Y-%m-%d")
            await execute("INSERT INTO contests(creator_id,title,prize,end_date) VALUES(?,?,?,?)", uid, context.user_data.get("ctitle",""), context.user_data.get("cprize",""), end.isoformat())
            await update.message.reply_text("✅")
        except: await update.message.reply_text("❌")
        context.user_data.clear()

async def group_msg(update: Update, context):
    if update.effective_chat.type not in ["group","supergroup"] or update.effective_user.is_bot: return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = update.message.text or ""

    settings = await fetch("SELECT * FROM group_settings WHERE chat_id=?", chat_id)
    lock_links = lock_mentions = 0
    if settings:
        s = dict(settings[0])
        lock_links = s.get('lock_links', 0)
        lock_mentions = s.get('lock_mentions', 0)

    if lock_links and await has_links(text):
        try: await update.message.delete()
        except: pass
        await auto_penalty(context.bot, chat_id, user_id)
        return
    if lock_mentions and await has_mentions(text):
        try: await update.message.delete()
        except: pass
        await auto_penalty(context.bot, chat_id, user_id)
        return

    words = _banned_cache.get(chat_id, []) + _banned_cache.get(-1, [])
    for word in words:
        if word in text.lower():
            try: await update.message.delete()
            except: pass
            await auto_penalty(context.bot, chat_id, user_id)
            return

    r = await fetch("SELECT reply FROM replies WHERE keyword=?", text.lower())
    if r: return await update.message.reply_text(r[0]['reply'])
    replies = {"مرحباً":"أهلاً 🤍", "السلام عليكم":"وعليكم السلام 🌹", "شكراً":"العفو"}
    for k,v in replies.items():
        if k in text.lower():
            await update.message.reply_text(v)
            break
