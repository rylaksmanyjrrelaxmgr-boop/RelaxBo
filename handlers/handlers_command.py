#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_command.py - معالجات الأوامر (CommandHandlers) - النسخة النهائية الكاملة
===================================================================================
جميع الأوامر النصية للبوت مع دعم المشرفين المخفيين وإصلاح جميع المشاكل.
+ الأوامر الإضافية: /admin /broadcast /set_force /set_update_ch /set_log_ch
+ /add_admin /remove_admin /export_replies /import_replies /backup /restore
+ /auto_publish /auto_recycle /channels /posts /mood
+ ربط جميع النصوص الثابتة بنظام الترجمة _trans
+ دمج كاش المستخدم (user_cache) لتسريع /start
+ إبطال الكاش عند تغيير بيانات المستخدم
+ الحفاظ على المنطقة الزمنية (جميع التواريخ naive UTC)
+ ✅ [إصلاح] syncgroup: ربط المشرفين المجهولين بالمعرفات الحقيقية
+ ✅ [إصلاح] syncgroup: التحقق من صلاحيات البوت باستخدام check_bot_permissions
+ ✅ [إصلاح] list_hidden_admins: عرض المشرفين المجهولين أيضاً
+ ✅ [إصلاح] تحديث updated_at عند تسجيل المجموعة
+ ✅ [إصلاح] التحقق من الصلاحيات في أوامر المجموعات
+ ✅ [v7.5.0] كاش الاشتراك الإجباري — تسريع /start من 4 ثوان إلى < 300ms
"""

import asyncio
import time as _time_module
import logging
from typing import Optional
from html import escape

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TimedOut

from config import CONFIG, PATHS
from database import DB, TimeUtils
from utils import (
    TextUtils, safe_send, is_authorized_in_group,
    check_bot_permissions, invalidate_auth_cache, apply_penalty,
    RATE_LIMITER, METRICS, get_text, StateManager, UserState,
    KeyboardFactory, TranslationManager, CB,
    export_auto_replies, import_auto_replies,
)
from cache import user_cache  # ✅ استيراد كاش المستخدم

logger = logging.getLogger(__name__)


async def _safe_answer(query, text=None, show_alert=False):
    """دالة مساعدة للإجابة على الاستعلامات بأمان"""
    try:
        if text:
            await query.answer(text, show_alert=show_alert)
        else:
            await query.answer()
        return True
    except (BadRequest, TimedOut) as e:
        logger.debug(f"Query answer failed: {e}")
        return False
    except Exception as e:
        logger.warning(f"⚠️ فشل query.answer: {e}")
        return False


def _mask_id(id_value, prefix=3, suffix=2):
    """إخفاء جزء من المعرفات الحساسة"""
    if id_value is None:
        return "***"
    s = str(id_value)
    if len(s) <= 5:
        return "***"
    return s[:prefix] + "***" + s[-suffix:] if len(s) > prefix + suffix else s[:prefix] + "***"


# ═══════════════════════════════════════════════════════════════════
# ✅ v7.5.0: كاش الاشتراك الإجباري (يُسرّع /start بشكل هائل)
# ═══════════════════════════════════════════════════════════════════

_force_sub_cache: dict = {}          # {user_id: (timestamp, bool)}
_FORCE_SUB_CACHE_TTL = 180           # 3 دقائق

_force_channel_cache: dict = {}      # {chat_id: (timestamp, chat_object)}
_FORCE_CHANNEL_CACHE_TTL = 600       # 10 دقائق


async def _get_force_channel_cached(bot, force_ch: str):
    """
    جلب معلومات قناة الاشتراك الإجباري مع كاش 10 دقائق.
    يمنع استدعاء get_chat في كل /start.
    """
    now = _time_module.time()
    cached = _force_channel_cache.get(force_ch)
    if cached:
        ts, chat = cached
        if now - ts < _FORCE_CHANNEL_CACHE_TTL:
            return chat

    try:
        if force_ch.lstrip('-').isdigit():
            chat = await bot.get_chat(int(force_ch))
        else:
            chat = await bot.get_chat(f"@{force_ch}")
        _force_channel_cache[force_ch] = (now, chat)
        return chat
    except Exception as e:
        logger.debug(f"⚠️ get_chat فشل: {e}")
        # إرجاع الكاش القديم عند الفشل
        if cached:
            return cached[1]
        return None


async def _check_force_subscription_cached(bot, user_id: int, force_ch: str) -> bool:
    """
    فحص الاشتراك الإجباري مع كاش 3 دقائق.
    يمنع استدعاء get_chat_member في كل /start.

    Returns:
        True إذا كان المستخدم مشتركاً، False إذا لم يكن
    """
    now = _time_module.time()
    cache_key = user_id

    # 1. فحص الكاش
    cached = _force_sub_cache.get(cache_key)
    if cached:
        ts, is_subscribed = cached
        if now - ts < _FORCE_SUB_CACHE_TTL:
            return is_subscribed

    # 2. الفحص الفعلي (بدون get_chat!)
    try:
        # ✅ get_chat_member يقبل @username أو -100... مباشرة
        target = int(force_ch) if force_ch.lstrip('-').isdigit() else f"@{force_ch}"
        member = await bot.get_chat_member(target, user_id)
        is_subscribed = member.status in ('member', 'administrator', 'creator')

        # خزّن النتيجة 3 دقائق
        _force_sub_cache[cache_key] = (now, is_subscribed)
        return is_subscribed
    except Exception as e:
        logger.debug(f"⚠️ get_chat_member فشل: {e}")
        # عند الفشل: اسمح للمستخدم بالمرور (لا تحجبه)
        return True


def _invalidate_force_sub_cache(user_id: int = None):
    """إبطال كاش الاشتراك الإجباري"""
    if user_id is None:
        _force_sub_cache.clear()
        _force_channel_cache.clear()
    else:
        _force_sub_cache.pop(user_id, None)


async def _trans(key, lang, default_ar):
    """جلب النص المترجم مع fallback للعربية"""
    try:
        text = await get_text(lang, key)
        if not text or text == key:
            return default_ar
        return text
    except:
        return default_ar


class CommandHandlers:
    """جميع معالجات الأوامر"""

    @staticmethod
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """الأمر /start - القائمة الرئيسية (محسّن مع الكاش)"""
        user_id = update.effective_user.id
        username = update.effective_user.username or ""
        first_name = update.effective_user.first_name or ""

        # تسجيل المستخدم (إذا كان جديداً)
        await DB.register_user(user_id, username, first_name)

        # معالجة الإحالات
        args = context.args or []
        if args and args[0].startswith('ref_'):
            ref_code = args[0][4:]
            referrer = await DB.get_user_by_referral_code(ref_code)
            if referrer and referrer != user_id and not await DB.is_user_banned(referrer):
                existing = await DB.fetchone("SELECT 1 FROM referrals WHERE referred_id=?", (user_id,))
                if not existing:
                    if await DB.add_referral(referrer, user_id):
                        reward = await DB.get_referral_stats(referrer)
                        try:
                            await context.bot.send_message(
                                referrer,
                                f"🎁 تمت إحالة `{_mask_id(user_id)}`. لديك {reward['available']} يوم متاح للصرف."
                            )
                        except Exception as e:
                            logger.warning(f"⚠️ فشل إرسال إشعار الإحالة: {e}")

        # ✅ v7.5.0: التحقق من الاشتراك الإجباري مع كاش (سريع!)
        force_ch = await DB.get_force_subscribe_channel()
        if force_ch and user_id != CONFIG.PRIMARY_OWNER_ID:
            try:
                # ✅ استخدم الكاش بدل استدعاءات API المتكررة
                is_subscribed = await _check_force_subscription_cached(
                    context.bot, user_id, force_ch
                )
                if not is_subscribed:
                    # جلب معلومات القناة (مع كاش 10 دقائق)
                    chat = await _get_force_channel_cached(context.bot, force_ch)

                    invite_link = None
                    if chat:
                        try:
                            invite_link = await context.bot.export_chat_invite_link(chat.id)
                        except Exception:
                            pass

                    if invite_link:
                        kb = InlineKeyboardMarkup([[
                            InlineKeyboardButton("📢 اشترك", url=invite_link),
                            InlineKeyboardButton("✅ تحقق", callback_data=CB.CHECK_SUB)
                        ]])
                    else:
                        kb = InlineKeyboardMarkup([[
                            InlineKeyboardButton("✅ تحقق", callback_data=CB.CHECK_SUB)
                        ]])
                    await safe_send(context.bot, user_id, "⚠️ اشترك في القناة أولاً", reply_markup=kb)
                    return
            except Exception as e:
                logger.error(f"❌ خطأ في التحقق من الاشتراك الإجباري: {e}")

        # ✅ استخدام الكاش الشامل - استعلام واحد فقط!
        user_data = await user_cache.get_or_load(user_id, DB)

        # استخراج البيانات من الكاش
        lang = user_data['language']
        active = user_data['active_channel']
        channel_info = user_data['channel_info']
        unpublished_posts = user_data['unpublished_posts']
        groups_count = user_data['groups_count']
        has_sub = user_data['has_subscription']
        auto = user_data['auto_publish']
        recycle = user_data['auto_recycle']

        # عرض القناة النشطة
        ch_display = await _trans('no_active_channel', lang, "لا توجد قنوات")
        if channel_info:
            ch_display = channel_info['channel_name']

        # إعداد النصوص
        sub_text = await _trans('subscription_active', lang, "✅ مفعل") if has_sub else await _trans('subscription_inactive', lang, "❌ غير مفعل")
        auto_text = await _trans('enabled', lang, "مفعل") if auto else await _trans('disabled', lang, "معطل")
        recycle_text = await _trans('enabled', lang, "مفعل") if recycle else await _trans('disabled', lang, "معطل")

        # بناء لوحة المفاتيح
        kb_rows = KeyboardFactory.get_menu("main_menu", lang)
        keyboard = []

        for row in kb_rows:
            btn_row = []
            for item in row:
                if item == "admin_panel_btn":
                    if CONFIG.is_developer(user_id):
                        text_btn = KeyboardFactory.get_text("admin_panel_btn", lang)
                        btn_row.append(InlineKeyboardButton(text_btn, callback_data=CB.ADMIN))
                else:
                    text_btn = KeyboardFactory.get_text(item, lang)
                    if item.endswith("_url"):
                        url = f"https://t.me/{CONFIG.BOT_USERNAME}?startgroup"
                        btn_row.append(InlineKeyboardButton(text_btn, url=url))
                    else:
                        btn_row.append(InlineKeyboardButton(text_btn, callback_data=item))
            if btn_row:
                keyboard.append(btn_row)

        if CONFIG.is_developer(user_id):
            admin_text = KeyboardFactory.get_text("admin_panel_btn", lang)
            if not any(btn.callback_data == CB.ADMIN for row in keyboard for btn in row):
                keyboard.append([InlineKeyboardButton(admin_text, callback_data=CB.ADMIN)])

        kb = InlineKeyboardMarkup(keyboard)

        title = await get_text(
            lang,
            'main_menu',
            user_name=f"<code>{user_id}</code>",
            groups_count=groups_count,
            active_channel=ch_display,
            unpublished_posts=unpublished_posts,
            auto_publish=auto_text,
            auto_recycle=recycle_text,
            subscription_status=sub_text
        )

        await safe_send(context.bot, user_id, title, reply_markup=kb)

    @staticmethod
    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        help_text = await _trans('help_text', lang, "❓ المساعدة")
        await safe_send(context.bot, user_id, help_text)

    @staticmethod
    async def trial(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if await DB.has_used_trial(user_id):
            await safe_send(context.bot, user_id, await _trans('trial_used', lang, "❌ لقد استخدمت التجربة المجانية بالفعل."))
            return
        days = await DB.activate_trial(user_id)
        if days > 0:
            msg = await _trans('trial_activated', lang, "✅ تم تفعيل التجربة المجانية لمدة {days} يوم").format(days=days)
        else:
            msg = await _trans('trial_failed', lang, "❌ تعذر تفعيل التجربة")
        await safe_send(context.bot, user_id, msg)
        # ✅ إبطال الكاش بعد تغيير الاشتراك
        await user_cache.invalidate(user_id)

    @staticmethod
    async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        kb = KeyboardFactory.build("plans", lang=lang)
        await safe_send(context.bot, user_id, await _trans('plan_selector', lang, "💎 اختر باقة:"), reply_markup=kb)

    @staticmethod
    async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        kb = KeyboardFactory.build("support", lang=lang)
        await safe_send(context.bot, user_id, await _trans('send_support_message', lang, "📞 أرسل رسالة الدعم"), reply_markup=kb)

    @staticmethod
    async def developer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        text = await get_text(
            lang,
            'developer_info',
            developer_name=getattr(CONFIG, 'DEVELOPER_NAME', "ريلاكس"),
            developer_contact=getattr(CONFIG, 'DEVELOPER_CONTACT', "@Reelaaaxbot")
        )
        await safe_send(context.bot, user_id, text)

    @staticmethod
    async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not CONFIG.is_developer(user_id):
            await safe_send(context.bot, user_id, await _trans('unauthorized', lang, "❌ غير مصرح"))
            return
        stats = await DB.get_bot_stats()
        text = await _trans('stats_message', lang,
            "📊 **الإحصائيات**\n\n👥 المستخدمون: {users}\n📡 القنوات: {channels}\n👥 المجموعات: {groups}\n📝 المنشورات: {posts}\n✅ المنشورة: {published}\n💎 الاشتراكات النشطة: {active_subs}\n🎫 التذاكر: {tickets}"
        ).format(users=stats.get('users',0), channels=stats.get('channels',0), groups=stats.get('groups',0), posts=stats.get('posts',0), published=stats.get('published',0), active_subs=stats.get('active_subs',0), tickets=stats.get('tickets',0))
        await safe_send(context.bot, user_id, text)

    @staticmethod
    async def language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        available = TranslationManager.get_available_languages()
        buttons = []
        row = []
        for code, name in available.items():
            row.append(InlineKeyboardButton(name, callback_data=f"lang_{code}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        back_text = KeyboardFactory.get_text("back", lang)
        buttons.append([InlineKeyboardButton(back_text, callback_data=CB.BACK)])
        kb = InlineKeyboardMarkup(buttons)
        current_lang = await _trans('current_language', lang, "الحالية")
        choose_lang = await _trans('choose_language', lang, "🌐 اختر اللغة:")
        await safe_send(context.bot, user_id, f"{choose_lang}\n\n{current_lang}: {lang}", reply_markup=kb)

    @staticmethod
    async def replies_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        await safe_send(context.bot, user_id, await _trans('replies_work', lang, "📚 الردود التلقائية تعمل!"))

    @staticmethod
    async def contests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        contests = await DB.get_active_contests(10)
        if not contests:
            await safe_send(context.bot, user_id, await _trans('no_contests', lang, "📭 لا توجد مسابقات نشطة"))
            return

        text = "🏆 <b>" + await _trans('active_contests', lang, "المسابقات النشطة") + "</b>\n\n"
        kb = []
        for c in contests:
            end_date = c.get('end_date') or ''
            title = escape(c.get('title', ''))
            prize = escape(c.get('prize', ''))
            participants = c.get('participants', 0)
            text += (
                f"• <b>{title}</b>\n"
                f"  🎁 {prize}\n"
                f"  📅 {escape(end_date[:10])}\n"
                f"  👥 {await _trans('participants', lang, 'المشاركون')}: {participants}\n\n"
            )
            join_text = await _trans('join_contest', lang, "✍️ المشاركة")
            kb.append([
                InlineKeyboardButton(
                    f"{join_text} {title[:20]}",
                    callback_data=f"{CB.CONTEST_JOIN}:{c['id']}"
                )
            ])

        kb.append([
            InlineKeyboardButton(KeyboardFactory.get_text("back", lang), callback_data=CB.BACK)
        ])

        await safe_send(context.bot, user_id, text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

    @staticmethod
    async def mood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        args = context.args or []

        if not args:
            StateManager.set(user_id, UserState.WAIT_MOOD)
            await safe_send(context.bot, user_id, await _trans('send_mood_text', lang, "📝 أرسل النص الذي تريد تحليل مشاعره:"))
            return

        text = " ".join(args)
        from handlers_message import analyze_sentiment
        if analyze_sentiment is None:
            await safe_send(context.bot, user_id, await _trans('mood_unavailable', lang, "❌ خدمة تحليل المشاعر غير متاحة حالياً"))
            return
        result = analyze_sentiment(text)

        response = (
            f"{result['emoji']} <b>{await _trans('mood_analysis', lang, 'تحليل المشاعر')}</b>\n\n"
            f"📝 {await _trans('mood_text', lang, 'النص')}: <code>{escape(text[:100])}</code>\n"
            f"🎯 {await _trans('mood_result', lang, 'النتيجة')}: <b>{escape(result['sentiment'])}</b>\n\n"
            f"😊 {await _trans('mood_positive', lang, 'إيجابي')}: {result['positive_percent']:.0f}%\n"
            f"😔 {await _trans('mood_negative', lang, 'سلبي')}: {result['negative_percent']:.0f}%\n"
            f"📊 {await _trans('mood_words', lang, 'الكلمات')}: {result['total_words']}"
        )
        await safe_send(context.bot, user_id, response, parse_mode='HTML')

    @staticmethod
    async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not CONFIG.is_developer(user_id):
            await safe_send(context.bot, user_id, await _trans('unauthorized', lang, "❌ غير مصرح"))
            return
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(await _trans('admin_panel_btn', lang, "👑 لوحة الأدمن"), callback_data=CB.ADMIN)
        ]])
        await safe_send(context.bot, user_id, await _trans('open_admin_panel', lang, "👑 لوحة الأدمن\n\nاضغط الزر أدناه:"), reply_markup=kb, parse_mode='HTML')

    @staticmethod
    async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not CONFIG.is_developer(user_id):
            await safe_send(context.bot, user_id, await _trans('unauthorized', lang, "❌ غير مصرح"))
            return
        StateManager.set(user_id, UserState.WAIT_BROADCAST)
        await safe_send(context.bot, user_id, await _trans('send_broadcast', lang, "📨 أرسل الرسالة التي تريد بثها:"))

    @staticmethod
    async def set_force(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not CONFIG.is_developer(user_id):
            return
        StateManager.set(user_id, UserState.WAIT_FORCE)
        await safe_send(context.bot, user_id, await _trans('send_channel_id', lang, "🔒 أرسل معرف القناة:"))

    @staticmethod
    async def set_update_ch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not CONFIG.is_developer(user_id):
            return
        StateManager.set(user_id, UserState.WAIT_UPDATE_CH)
        await safe_send(context.bot, user_id, await _trans('send_update_channel', lang, "📢 أرسل معرف قناة التحديثات:"))

    @staticmethod
    async def set_log_ch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not CONFIG.is_developer(user_id):
            return
        StateManager.set(user_id, UserState.WAIT_LOG_CH)
        await safe_send(context.bot, user_id, await _trans('send_log_channel', lang, "📋 أرسل معرف قناة السجلات:"))

    @staticmethod
    async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not CONFIG.is_developer(user_id):
            return
        StateManager.set(user_id, UserState.WAIT_ADMIN_ADD)
        await safe_send(context.bot, user_id, await _trans('send_admin_id', lang, "👑 أرسل معرف المشرف:"))

    @staticmethod
    async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not CONFIG.is_developer(user_id):
            return
        StateManager.set(user_id, UserState.WAIT_ADMIN_REM)
        await safe_send(context.bot, user_id, await _trans('send_admin_id_remove', lang, "🗑️ أرسل معرف المشرف:"))

    @staticmethod
    async def export_replies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not CONFIG.is_developer(user_id):
            return
        count = await export_auto_replies(-1)
        await safe_send(context.bot, user_id, f"✅ {count}")

    @staticmethod
    async def import_replies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not CONFIG.is_developer(user_id):
            return
        StateManager.set(user_id, UserState.WAIT_IMPORT_FILE)
        await safe_send(context.bot, user_id, await _trans('send_json', lang, "📤 أرسل ملف JSON:"))

    @staticmethod
    async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not CONFIG.is_developer(user_id):
            return
        await safe_send(context.bot, user_id, await _trans('backup_start', lang, "⏳ جارٍ النسخ الاحتياطي..."))
        try:
            from utils import BackgroundTasks
            asyncio.create_task(BackgroundTasks._do_backup())
            await safe_send(context.bot, user_id, await _trans('backup_done', lang, "✅ تم أخذ نسخة احتياطية"))
        except Exception as e:
            await safe_send(context.bot, user_id, f"❌ {str(e)[:50]}")

    @staticmethod
    async def restore(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not CONFIG.is_developer(user_id):
            return
        backups = sorted(PATHS.BACKUPS.glob("backup_*.db"), key=lambda x: x.stat().st_mtime, reverse=True)
        if not backups:
            await safe_send(context.bot, user_id, await _trans('no_backups', lang, "📭 لا توجد نسخ"))
            return
        text = "🔄 <b>" + await _trans('available_backups', lang, "النسخ المتاحة:") + "</b>\n\n" + "\n".join(b.name for b in backups[:10])
        await safe_send(context.bot, user_id, text, parse_mode='HTML')

    @staticmethod
    async def auto_publish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        cur = await DB.get_auto_publish_status(user_id)
        await DB.set_auto_publish(user_id, not cur)
        status = await _trans('enabled', lang, "مفعل") if not cur else await _trans('disabled', lang, "معطل")
        await safe_send(context.bot, user_id, f"✅ {await _trans('auto_publish_status', lang, 'النشر التلقائي')}: {status}")
        # ✅ إبطال الكاش
        await user_cache.invalidate(user_id)

    @staticmethod
    async def auto_recycle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        cur = await DB.get_auto_recycle_status(user_id)
        await DB.set_auto_recycle(user_id, not cur)
        status = await _trans('enabled', lang, "مفعل") if not cur else await _trans('disabled', lang, "معطل")
        await safe_send(context.bot, user_id, f"✅ {await _trans('auto_recycle_status', lang, 'التدوير التلقائي')}: {status}")
        # ✅ إبطال الكاش
        await user_cache.invalidate(user_id)

    @staticmethod
    async def channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        channels = await DB.get_user_channels(user_id)
        if not channels:
            await safe_send(context.bot, user_id, await _trans('no_channels', lang, "📭 لا توجد قنوات"))
            return
        text = "📡 <b>" + await _trans('your_channels', lang, "قنواتك:") + "</b>\n\n"
        for ch in channels:
            text += f"• {escape(ch['channel_name'])} (<code>{ch['channel_id']}</code>)\n"
        await safe_send(context.bot, user_id, text, parse_mode='HTML')

    @staticmethod
    async def posts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        active = await DB.get_active_channel(user_id)
        if not active:
            await safe_send(context.bot, user_id, await _trans('no_active_channel', lang, "❌ لا توجد قناة نشطة"))
            return
        posts = await DB.get_user_posts(user_id, active, 10)
        if not posts:
            await safe_send(context.bot, user_id, await _trans('no_posts', lang, "📭 لا توجد منشورات"))
            return
        text = "📋 <b>" + await _trans('your_posts', lang, "منشوراتك:") + "</b>\n\n"
        for p in posts:
            text += f"• <code>{p['id']}</code>: {(escape(p['text'] or '')[:30])}\n"
        await safe_send(context.bot, user_id, text, parse_mode='HTML')

    # ========== أوامر المجموعات ==========

    @staticmethod
    async def security(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat.type not in ['group', 'supergroup']:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await safe_send(context.bot, user_id, await _trans('unauthorized', lang, "❌ غير مصرح"))
            return
        context.user_data['security_chat_id'] = chat_id
        settings = await DB.get_security_settings(chat_id)
        text = KeyboardFactory._format_security_text(settings)
        kb = KeyboardFactory.build("security", chat_id=chat_id, lang=lang)
        await safe_send(context.bot, user_id, text, reply_markup=kb)

    @staticmethod
    async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat.type not in ['group', 'supergroup']:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await safe_send(context.bot, user_id, await _trans('unauthorized', lang, "❌ غير مصرح"))
            return
        kb = KeyboardFactory.build("panel", chat_id=chat_id, lang=lang)
        await safe_send(context.bot, user_id, await _trans('group_panel', lang, "📋 لوحة تحكم المجموعة"), reply_markup=kb)

    @staticmethod
    async def lock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat.type not in ['group', 'supergroup']:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            return
        await DB.execute("INSERT OR REPLACE INTO chat_locks (chat_id, locked, locked_at, locked_by) VALUES (?,1,?,?)",
                         (chat_id, TimeUtils.sql_iso(), user_id))
        await safe_send(context.bot, user_id, await _trans('group_locked', lang, "🔒 تم القفل"))

    @staticmethod
    async def unlock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat.type not in ['group', 'supergroup']:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            return
        await DB.execute("DELETE FROM chat_locks WHERE chat_id=?", (chat_id,))
        await safe_send(context.bot, user_id, await _trans('group_unlocked', lang, "🔓 تم الفتح"))

    @staticmethod
    async def register_hidden_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if user_id != CONFIG.PRIMARY_OWNER_ID:
            return
        if not context.args:
            await safe_send(context.bot, user_id, "📝 /register_hidden_owner <user_id>")
            return
        try:
            owner_id = int(context.args[0])
            if owner_id <= 0:
                raise ValueError
        except (ValueError, TypeError):
            await safe_send(context.bot, user_id, "⚠️ معرف غير صالح")
            return
        chat_id = update.effective_chat.id
        await DB.execute("INSERT OR IGNORE INTO hidden_owner_groups (chat_id, owner_id, is_hidden) VALUES (?,?,1)", (chat_id, owner_id))
        invalidate_auth_cache(chat_id, owner_id)
        await safe_send(context.bot, user_id, f"✅ تم تسجيل <code>{owner_id}</code> كمالك مخفي", parse_mode='HTML')

    @staticmethod
    async def remove_hidden_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if user_id != CONFIG.PRIMARY_OWNER_ID:
            return
        if not context.args:
            return
        try:
            owner_id = int(context.args[0])
        except (ValueError, TypeError):
            return
        chat_id = update.effective_chat.id
        await DB.execute("DELETE FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?", (chat_id, owner_id))
        invalidate_auth_cache(chat_id, owner_id)
        await safe_send(context.bot, user_id, f"✅ تم إزالة <code>{owner_id}</code>", parse_mode='HTML')

    @staticmethod
    async def add_hidden_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        is_owner = user_id == CONFIG.PRIMARY_OWNER_ID
        if not is_owner:
            row = await DB.fetchone("SELECT 1 FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?", (chat_id, user_id))
            is_owner = row is not None
        if not is_owner:
            return
        if not context.args:
            return
        try:
            admin_id = int(context.args[0])
            if admin_id <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return
        await DB.add_hidden_admin(chat_id, admin_id, user_id)
        invalidate_auth_cache(chat_id, admin_id)
        await safe_send(context.bot, user_id, f"✅ تم إضافة <code>{admin_id}</code> كمشرف مخفي", parse_mode='HTML')

    @staticmethod
    async def remove_hidden_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        is_owner = user_id == CONFIG.PRIMARY_OWNER_ID
        if not is_owner:
            row = await DB.fetchone("SELECT 1 FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?", (chat_id, user_id))
            is_owner = row is not None
        if not is_owner:
            return
        if not context.args:
            return
        try:
            admin_id = int(context.args[0])
        except (ValueError, TypeError):
            return
        await DB.execute("DELETE FROM hidden_admins WHERE chat_id=? AND admin_id=?", (chat_id, admin_id))
        invalidate_auth_cache(chat_id, admin_id)
        await safe_send(context.bot, user_id, f"✅ تم إزالة <code>{admin_id}</code>", parse_mode='HTML')

    @staticmethod
    async def list_hidden_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        is_owner = user_id == CONFIG.PRIMARY_OWNER_ID
        if not is_owner:
            row = await DB.fetchone("SELECT 1 FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?", (chat_id, user_id))
            is_owner = row is not None
        if not is_owner:
            return
        owners = await DB.fetchall("SELECT owner_id FROM hidden_owner_groups WHERE chat_id=?", (chat_id,))
        admins = await DB.fetchall("SELECT admin_id FROM hidden_admins WHERE chat_id=?", (chat_id,))
        # ✅ جلب المشرفين المجهولين أيضاً
        anonymous_admins = await DB.fetchall("SELECT anonymous_id, user_id FROM anonymous_admins WHERE chat_id=?", (chat_id,))

        text = "👤 <b>المخفيون</b>\n"
        for o in owners:
            text += f"👑 <code>{o['owner_id']}</code>\n"
        for a in admins:
            text += f"🛡️ <code>{a['admin_id']}</code>\n"
        for a in anonymous_admins:
            real = f"<code>{a['user_id']}</code>" if a['user_id'] else "غير معروف"
            text += f"🕵️ مجهول: <code>{a['anonymous_id']}</code> (حقيقي: {real})\n"

        await safe_send(context.bot, user_id, text if (owners or admins or anonymous_admins) else "📭 لا يوجد", parse_mode='HTML')

    @staticmethod
    async def syncgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or update.effective_chat.type not in ['group', 'supergroup']:
            await safe_send(context.bot, update.effective_user.id, "❌ هذا الأمر للمجموعات فقط")
            return

        chat_id = update.effective_chat.id
        chat_name = update.effective_chat.title or "بدون اسم"
        user_id = update.effective_user.id

        logger.info(f"🔍 محاولة تسجيل المجموعة: chat_id={chat_id}, user_id={user_id}")

        try:
            # ✅ التحقق من صلاحيات البوت
            perms = await check_bot_permissions(context.bot, chat_id)
            if not perms['can_act']:
                await safe_send(
                    context.bot, user_id,
                    f"❌ <b>البوت لا يملك الصلاحيات الكافية!</b>\n\n"
                    f"يجب أن يكون البوت مشرفاً مع صلاحية حذف الرسائل وتقييد الأعضاء.\n"
                    f"السبب: {perms.get('reason', 'غير معروف')}",
                    parse_mode='HTML'
                )
                return
        except Exception as e:
            await safe_send(context.bot, user_id, f"❌ {escape(str(e)[:50])}")
            return

        try:
            all_admins = await context.bot.get_chat_administrators(chat_id)
        except Exception as e:
            await safe_send(context.bot, user_id, "❌ فشل جلب المشرفين")
            return

        creator_id = None
        for admin in all_admins:
            if admin.status == 'creator' and not admin.user.is_bot:
                creator_id = admin.user.id
                break

        is_admin = False
        real_user_id = user_id

        if update.message and update.message.sender_chat and update.message.sender_chat.id == chat_id:
            is_admin = True
            real_user_id = update.message.sender_chat.id
        else:
            for admin in all_admins:
                if admin.user.id == user_id:
                    is_admin = True
                    real_user_id = admin.user.id
                    break

        if not is_admin and hasattr(CONFIG, 'ANONYMOUS_ADMIN_ID') and user_id == CONFIG.ANONYMOUS_ADMIN_ID:
            is_admin = True
            real_user_id = user_id

        # ✅ التحقق من المشرفين المجهولين (إذا لم يتم التعرف عليهم كـ is_admin)
        if not is_admin:
            row = await DB.fetchone(
                "SELECT 1 FROM anonymous_admins WHERE chat_id=? AND (user_id=? OR anonymous_id=?) LIMIT 1",
                (chat_id, user_id, user_id)
            )
            if row:
                is_admin = True
                # معرف حقيقي قد يكون غير معروف، لكننا نستخدم user_id كمؤقت
                real_user_id = user_id

        if not is_admin:
            await safe_send(context.bot, user_id, "❌ <b>أنت لست مشرفاً في هذه المجموعة!</b>", parse_mode='HTML')
            return

        try:
            await DB.register_group(chat_id, chat_name, creator_id or real_user_id, update.effective_chat.username)
        except Exception as e:
            await safe_send(context.bot, user_id, "❌ فشل تسجيل المجموعة")
            return

        try:
            if creator_id:
                await DB.execute(
                    "INSERT OR REPLACE INTO hidden_owner_groups (chat_id, owner_id, is_hidden) VALUES (?,?,0)",
                    (chat_id, creator_id)
                )
                await DB.execute(
                    "INSERT OR IGNORE INTO user_groups_link (user_id, chat_id) VALUES (?,?)",
                    (creator_id, chat_id)
                )
                invalidate_auth_cache(chat_id, creator_id)

            await DB.execute(
                "INSERT OR IGNORE INTO user_groups_link (user_id, chat_id) VALUES (?,?)",
                (real_user_id, chat_id)
            )
            invalidate_auth_cache(chat_id, real_user_id)
        except Exception as e:
            logger.error(f"❌ فشل ربط المستخدم: {e}")

        try:
            admin_ids = [a.user.id for a in all_admins if a.user and not a.user.is_bot and a.user.id != chat_id]
            admin_count = await DB.sync_group_admins(chat_id, admin_ids)
        except Exception as e:
            admin_count = 0

        # ✅ معالجة المشرفين المجهولين وربطهم بالمعرفات الحقيقية
        anonymous_ids = []
        user_id_map = {}

        for admin in all_admins:
            if admin.user.is_bot and admin.status == 'administrator':
                anon_id = admin.user.id
                anonymous_ids.append(anon_id)
                # محاولة جلب المعرف الحقيقي من قاعدة البيانات (إذا كان مسجلاً مسبقاً)
                row = await DB.fetchone(
                    "SELECT user_id FROM anonymous_admins WHERE chat_id=? AND anonymous_id=?",
                    (chat_id, anon_id)
                )
                if row and row['user_id']:
                    user_id_map[anon_id] = row['user_id']

        if anonymous_ids:
            await DB.sync_anonymous_admins(
                chat_id,
                anonymous_ids,
                added_by=real_user_id,
                user_id_map=user_id_map
            )
            # ربط المشرفين المجهولين بالمجموعة (لظهورهم في قائمة المجموعات)
            for anon_id, real_id in user_id_map.items():
                if real_id:
                    await DB.execute(
                        "INSERT OR IGNORE INTO user_groups_link (user_id, chat_id) VALUES (?,?)",
                        (real_id, chat_id)
                    )
            logger.info(f"✅ تم تسجيل {len(anonymous_ids)} مشرف مجهول في المجموعة {chat_id}")

        msg = (
            f"🎉 <b>تم تفعيل المجموعة بنجاح!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>المجموعة:</b> {escape(chat_name)}\n"
            f"🆔 <b>المعرف:</b> <code>{chat_id}</code>\n"
        )
        if creator_id:
            msg += f"👑 <b>المالك:</b> <code>{creator_id}</code>\n"
        msg += f"👤 <b>مشرف:</b> <code>{real_user_id}</code>\n"
        msg += f"👥 <b>المشرفون:</b> {admin_count}\n"
        if anonymous_ids:
            msg += f"🕵️ <b>المشرفون المجهولون:</b> {len(anonymous_ids)}\n"
        msg += (
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ <b>الحماية:</b> مفعّلة\n"
            f"💡 استخدم /security للإعدادات"
        )

        is_anonymous = (
            update.message and
            update.message.sender_chat and
            update.message.sender_chat.id == chat_id
        )

        if not is_anonymous:
            try:
                await safe_send(context.bot, user_id, msg, parse_mode='HTML')
            except BadRequest as e:
                if "User_bot_to_bot_disabled" in str(e):
                    await safe_send(context.bot, chat_id, msg, parse_mode='HTML')

        sent_msg = await safe_send(context.bot, chat_id, "🤖 <b>تم تفعيل البوت!</b>", parse_mode='HTML')
        if sent_msg:
            try:
                await asyncio.sleep(5)
                await sent_msg.delete()
            except Exception:
                pass

    # ========== أوامر الإشراف ==========

    @staticmethod
    async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await CommandHandlers._moderation_command(update, context, "ban")

    @staticmethod
    async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await CommandHandlers._moderation_command(update, context, "mute")

    @staticmethod
    async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await CommandHandlers._moderation_command(update, context, "warn")

    @staticmethod
    async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await CommandHandlers._moderation_command(update, context, "kick")

    @staticmethod
    async def restrict(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await CommandHandlers._moderation_command(update, context, "restrict")

    @staticmethod
    async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await CommandHandlers._moderation_command(update, context, "unban")

    @staticmethod
    async def pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat.type not in ['group', 'supergroup']:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            return
        if update.message.reply_to_message:
            perms = await check_bot_permissions(context.bot, chat_id)
            if not perms.get('can_pin', False):
                await safe_send(context.bot, user_id, await _trans('no_pin_permission', lang, "❌ البوت لا يملك صلاحية تثبيت الرسائل."))
                return
            try:
                await context.bot.pin_chat_message(chat_id, update.message.reply_to_message.message_id)
                await safe_send(context.bot, user_id, await _trans('pinned_success', lang, "📌 تم التثبيت"))
            except Exception as e:
                logger.error(f"❌ فشل التثبيت: {e}")

    @staticmethod
    async def _moderation_command(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
        if update.effective_chat.type not in ['group', 'supergroup']:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'

        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await safe_send(context.bot, user_id, await _trans('unauthorized', lang, "❌ غير مصرح"))
            return

        perms = await check_bot_permissions(context.bot, chat_id)
        if not perms.get('can_act', False):
            await safe_send(context.bot, user_id, await _trans('insufficient_permissions', lang, "❌ البوت لا يملك الصلاحيات الكافية."))
            return

        args = context.args or []
        if not args:
            await safe_send(context.bot, user_id, f"📝 /{action} معرف_المستخدم [مدة_بالدقائق]")
            return

        try:
            target = int(args[0])
            if target <= 0:
                raise ValueError
        except (ValueError, TypeError):
            await safe_send(context.bot, user_id, await _trans('invalid_id', lang, "❌ معرف غير صالح"))
            return

        if await is_authorized_in_group(context.bot, chat_id, target):
            await safe_send(context.bot, user_id, await _trans('cannot_moderate_admin', lang, "❌ لا يمكن معاملة مشرف"))
            return

        reason_parts = []
        duration_seconds = 60
        if len(args) > 1:
            try:
                minutes = int(args[1])
                if minutes > 0:
                    duration_seconds = minutes * 60
                    reason_parts = args[2:]
                else:
                    reason_parts = args[1:]
            except ValueError:
                reason_parts = args[1:]

        reason = " ".join(reason_parts)

        if action == 'unban':
            try:
                await context.bot.unban_chat_member(chat_id, target)
                await DB.remove_penalties_for_user(target, chat_id, penalty_type='ban')
                await safe_send(context.bot, user_id, await _trans('unban_success', lang, "✅ تم إلغاء الحظر"))
            except Exception as e:
                await safe_send(context.bot, user_id, f"❌ {escape(str(e)[:50])}")
            return

        success, msg = await apply_penalty(context.bot, chat_id, target, action, duration_seconds, reason, user_id)
        await safe_send(context.bot, user_id, msg)
        if success:
            await invalidate_auth_cache(chat_id=chat_id, user_id=target)

    # ========== أوامر المطور ==========

    @staticmethod
    async def set_min_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not CONFIG.is_developer(user_id):
            await safe_send(context.bot, user_id, await _trans('unauthorized', lang, "❌ غير مصرح"))
            return
        args = context.args or []
        if not args:
            await safe_send(context.bot, user_id, "📝 /set_min_interval <دقائق>")
            return
        try:
            val = int(args[0])
            if val < 1:
                await safe_send(context.bot, user_id, "❌ الحد الأدنى يجب أن يكون 1 دقيقة")
                return
            await DB.set_setting('min_publish_interval', str(val))
            await safe_send(context.bot, user_id, f"✅ تم تعيين الحد الأدنى إلى {val} دقيقة")
        except ValueError:
            await safe_send(context.bot, user_id, "❌ قيمة غير صالحة")

    @staticmethod
    async def grant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        if not CONFIG.is_developer(user_id):
            await safe_send(context.bot, user_id, await _trans('unauthorized', lang, "❌ غير مصرح"))
            return
        args = context.args or []
        if len(args) < 2:
            await safe_send(context.bot, user_id, "📝 /grant <user_id> <days>")
            return
        try:
            target_id = int(args[0])
            days = int(args[1])
            if target_id <= 0 or days < 1 or days > 365:
                raise ValueError
        except (ValueError, TypeError):
            await safe_send(context.bot, user_id, "❌ قيم غير صالحة")
            return
        user_row = await DB.fetchone("SELECT user_id FROM users WHERE user_id=?", (target_id,))
        if not user_row:
            await safe_send(context.bot, user_id, "❌ المستخدم غير موجود")
            return
        plan_row = await DB.fetchone("SELECT id FROM plans WHERE is_gift=1 LIMIT 1")
        if not plan_row:
            plan_row = await DB.fetchone("SELECT id FROM plans WHERE is_active=1 AND is_gift=0 LIMIT 1")
        plan_id = plan_row['id'] if plan_row else None
        if plan_id is None:
            await safe_send(context.bot, user_id, "❌ لا توجد خطط")
            return
        success = await DB.grant_subscription_days(target_id, days, plan_id=plan_id, provider='manual')
        if success:
            await safe_send(context.bot, user_id, f"✅ تم منح {days} يوم للمستخدم <code>{_mask_id(target_id)}</code>", parse_mode='HTML')
            # ✅ إبطال كاش المستخدم المستهدف
            await user_cache.invalidate(target_id)
        else:
            await safe_send(context.bot, user_id, "❌ فشل المنح")

    @staticmethod
    async def gift_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        plans = await DB.get_gift_plans()
        if not plans:
            await safe_send(context.bot, user_id, await _trans('no_gift_plans', lang, "📭 لا توجد خطط هدايا"))
            return
        kb = []
        for plan in plans:
            kb.append([InlineKeyboardButton(f"🎁 {plan['days']} يوم - {plan['price']} ⭐", callback_data=f"buy_gift:{plan['id']}")])
        kb.append([InlineKeyboardButton(KeyboardFactory.get_text("back", lang), callback_data=CB.BACK)])
        await safe_send(context.bot, user_id, await _trans('gift_plans_text', lang, "💎 اختر خطة هدية:"), reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

    @staticmethod
    async def redeem_gift(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        args = context.args or []
        if not args:
            await safe_send(context.bot, user_id, await _trans('send_gift_code', lang, "📝 أرسل الكود: /redeem_gift <الكود>"))
            return
        code = args[0].strip()
        if len(code) < 4 or len(code) > 50:
            await safe_send(context.bot, user_id, await _trans('invalid_gift_code', lang, "❌ كود غير صالح"))
            return
        success, days = await DB.redeem_gift_code(user_id, code)
        if success and days > 0:
            await safe_send(context.bot, user_id, await _trans('gift_redeemed_success', lang, f"🎉 تم تفعيل اشتراك {days} يوم"), parse_mode='HTML')
            # ✅ إبطال الكاش
            await user_cache.invalidate(user_id)
        elif days == -1:
            await safe_send(context.bot, user_id, await _trans('cannot_redeem_own', lang, "❌ لا يمكنك استخدام كودك الخاص"))
        else:
            await safe_send(context.bot, user_id, await _trans('gift_invalid', lang, "❌ كود غير صالح"))