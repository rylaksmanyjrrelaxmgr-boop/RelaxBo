#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_command.py - معالجات الأوامر (CommandHandlers) - نسخة محسّنة وموثوقة
=============================================================================
- استخدام asyncio.gather مع return_exceptions=True لتفادي توقف العملية
- معالجة فردية لكل نتيجة، مع قيم افتراضية عند الفشل
- تحسين التحقق من الاشتراك الإجباري: السماح بالدخول عند حدوث خطأ
- طبقة تخزين مؤقت بسيطة (In-Memory Cache) مع TTL = 10 دقائق
- الحفاظ على جميع الأوامر والإصلاحات السابقة
"""

import asyncio
import logging
from typing import Optional, Dict, Any
from html import escape
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TimedOut

from config import CONFIG, PATHS
from database import DB
from utils import (
    TimeUtils, TextUtils, safe_send, is_authorized_in_group,
    check_bot_permissions, invalidate_auth_cache, apply_penalty,
    RATE_LIMITER, METRICS, get_text, StateManager, UserState,
    KeyboardFactory, TranslationManager, CB,
    export_auto_replies, import_auto_replies,
)

logger = logging.getLogger(__name__)

# =====================================================================
# طبقة تخزين مؤقت بسيطة (In-Memory Cache) مع TTL = 10 دقائق
# =====================================================================
class SimpleCache:
    def __init__(self, ttl_seconds: int = 600):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._ttl = ttl_seconds

    def _key(self, *args) -> str:
        return ":".join(str(a) for a in args)

    def get(self, *args) -> Optional[Any]:
        key = self._key(*args)
        entry = self._cache.get(key)
        if entry and (datetime.utcnow() - entry['timestamp']).total_seconds() < self._ttl:
            return entry['value']
        return None

    def set(self, value: Any, *args) -> None:
        key = self._key(*args)
        self._cache[key] = {'value': value, 'timestamp': datetime.utcnow()}

    def invalidate(self, *args) -> None:
        key = self._key(*args)
        self._cache.pop(key, None)

    def clear(self) -> None:
        self._cache.clear()

CACHE = SimpleCache(ttl_seconds=600)


# =====================================================================
# دوال مساعدة
# =====================================================================
async def _get_cached_or_fetch(cache_key: str, user_id: int, fetch_func, default=None):
    """جلب قيمة من الكاش أو تنفيذ دالة الجلب ثم تخزينها. إذا فشلت، نعيد القيمة الافتراضية."""
    val = CACHE.get(cache_key, user_id)
    if val is not None:
        return val
    try:
        val = await fetch_func(user_id)
        if val is None:
            val = default
        CACHE.set(val, cache_key, user_id)
        return val
    except Exception as e:
        logger.error(f"❌ فشل جلب {cache_key} للمستخدم {user_id}: {e}", exc_info=True)
        return default


async def _check_force_subscription(bot, user_id: int) -> Dict[str, Any]:
    """
    التحقق من الاشتراك الإجباري مع تخزين مؤقت.
    تُرجع قاموسًا يحتوي على:
        - passed: bool (هل يمكنه الدخول)
        - invite_link: str أو None (إذا لزم)
        - error: bool (هل حدث خطأ أثناء التحقق)
    """
    cache_key = "force_sub"
    cached = CACHE.get(cache_key, user_id)
    if cached is not None:
        return cached

    result = {
        "passed": True,
        "invite_link": None,
        "error": False,
    }

    force_ch = None
    try:
        force_ch = await DB.get_force_subscribe_channel()
    except Exception as e:
        logger.error(f"❌ فشل جلب قناة الاشتراك الإجباري: {e}")
        result["error"] = True
        CACHE.set(result, cache_key, user_id)
        return result  # في حالة الخطأ نسمح بالدخول

    if not force_ch or user_id == CONFIG.PRIMARY_OWNER_ID:
        CACHE.set(result, cache_key, user_id)
        return result

    try:
        # جلب كائن الدردشة
        if force_ch.lstrip('-').isdigit():
            chat = await bot.get_chat(int(force_ch))
        else:
            chat = await bot.get_chat(f"@{force_ch}")

        # التحقق من عضوية المستخدم
        member = await bot.get_chat_member(chat.id, user_id)
        if member.status not in ['member', 'administrator', 'creator']:
            result["passed"] = False
            try:
                invite_link = await bot.export_chat_invite_link(chat.id)
                result["invite_link"] = invite_link
            except Exception as e:
                logger.warning(f"⚠️ فشل جلب رابط الدعوة: {e}")
                # في حالة فشل جلب الرابط، نترك invite_link = None
    except Exception as e:
        # إذا حدث خطأ في API، نسجل الخطأ ونعتبر أن المستخدم يمكنه الدخول لتجنب الحبس
        logger.error(f"❌ خطأ أثناء التحقق من الاشتراك للمستخدم {user_id}: {e}", exc_info=True)
        result["error"] = True
        result["passed"] = True  # السماح بالدخول عند الخطأ

    CACHE.set(result, cache_key, user_id)
    return result


async def _safe_answer(query, text=None, show_alert=False):
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
    if id_value is None:
        return "***"
    s = str(id_value)
    if len(s) <= 5:
        return "***"
    return s[:prefix] + "***" + s[-suffix:] if len(s) > prefix + suffix else s[:prefix] + "***"


async def _trans(key, lang, default_ar):
    try:
        text = await get_text(lang, key)
        if not text or text == key:
            return default_ar
        return text
    except:
        return default_ar


# =====================================================================
# معالجات الأوامر
# =====================================================================
class CommandHandlers:
    @staticmethod
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        username = update.effective_user.username or ""
        first_name = update.effective_user.first_name or ""

        # تسجيل المستخدم (سريع)
        try:
            await DB.register_user(user_id, username, first_name)
        except Exception as e:
            logger.error(f"❌ فشل تسجيل المستخدم {user_id}: {e}")

        # معالجة الإحالات (اختياري، في الخلفية)
        args = context.args or []
        if args and args[0].startswith('ref_'):
            try:
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
            except Exception as e:
                logger.error(f"❌ خطأ في معالجة الإحالة: {e}")

        # ===== جلب جميع البيانات المطلوبة بالتوازي مع معالجة الأخطاء =====
        # نستخدم asyncio.gather مع return_exceptions=True للحصول على كل نتيجة بشكل منفصل
        # حتى لو فشل بعضها، لا يفشل البقية.
        results = await asyncio.gather(
            _get_cached_or_fetch("lang", user_id, DB.get_user_language, 'ar'),
            _get_cached_or_fetch("active_channel", user_id, DB.get_active_channel, None),
            _get_cached_or_fetch("auto_publish", user_id, DB.get_auto_publish_status, False),
            _get_cached_or_fetch("auto_recycle", user_id, DB.get_auto_recycle_status, False),
            _get_cached_or_fetch("has_sub", user_id, DB.has_active_subscription, False),
            DB.get_user_groups(user_id),
            _check_force_subscription(context.bot, user_id),
            return_exceptions=True
        )

        # تفكيك النتائج مع تعويض أي فشل بالقيم الافتراضية
        lang = results[0] if not isinstance(results[0], Exception) else 'ar'
        active = results[1] if not isinstance(results[1], Exception) else None
        auto = results[2] if not isinstance(results[2], Exception) else False
        recycle = results[3] if not isinstance(results[3], Exception) else False
        has_sub = results[4] if not isinstance(results[4], Exception) else False
        groups = results[5] if not isinstance(results[5], Exception) else []
        force_sub_info = results[6] if not isinstance(results[6], Exception) else {"passed": True, "invite_link": None, "error": True}

        # التحقق من الاشتراك الإجباري
        if not force_sub_info.get("passed", True):
            invite_link = force_sub_info.get("invite_link")
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

        # تجهيز بيانات العرض
        cnt = 0
        ch_display = await _trans('no_active_channel', lang, "لا توجد قنوات")
        if active:
            try:
                cnt = await DB.get_unpublished_posts_count(user_id, active)
                ch_info = await DB.get_channel_info(user_id, active)
                if ch_info:
                    ch_display = ch_info['channel_name']
            except Exception as e:
                logger.error(f"❌ خطأ في جلب بيانات القناة النشطة: {e}")

        sub_active_text = await _trans('subscription_active', lang, "✅ مفعل")
        sub_inactive_text = await _trans('subscription_inactive', lang, "❌ غير مفعل")
        sub_text = sub_active_text if has_sub else sub_inactive_text

        enabled_text = await _trans('enabled', lang, "مفعل")
        disabled_text = await _trans('disabled', lang, "معطل")
        auto_text = enabled_text if auto else disabled_text
        recycle_text = enabled_text if recycle else disabled_text

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

        try:
            title = await get_text(
                lang,
                'main_menu',
                user_name=f"<code>{user_id}</code>",
                groups_count=len(groups),
                active_channel=ch_display,
                unpublished_posts=cnt,
                auto_publish=auto_text,
                auto_recycle=recycle_text,
                subscription_status=sub_text
            )
        except Exception as e:
            logger.error(f"❌ خطأ في توليد نص القائمة: {e}")
            title = "مرحبًا! استخدم الأزرار أدناه."

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
        CACHE.invalidate("has_sub", user_id)

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
        try:
            from handlers_message import analyze_sentiment
            if analyze_sentiment is None:
                raise ImportError
            result = analyze_sentiment(text)
        except Exception as e:
            logger.error(f"❌ فشل تحليل المشاعر: {e}")
            await safe_send(context.bot, user_id, await _trans('mood_unavailable', lang, "❌ خدمة تحليل المشاعر غير متاحة حالياً"))
            return

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
        CACHE.invalidate("auto_publish", user_id)

    @staticmethod
    async def auto_recycle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        cur = await DB.get_auto_recycle_status(user_id)
        await DB.set_auto_recycle(user_id, not cur)
        status = await _trans('enabled', lang, "مفعل") if not cur else await _trans('disabled', lang, "معطل")
        await safe_send(context.bot, user_id, f"✅ {await _trans('auto_recycle_status', lang, 'التدوير التلقائي')}: {status}")
        CACHE.invalidate("auto_recycle", user_id)

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
        text = "👤 <b>المخفيون</b>\n"
        for o in owners:
            text += f"👑 <code>{o['owner_id']}</code>\n"
        for a in admins:
            text += f"🛡️ <code>{a['admin_id']}</code>\n"
        await safe_send(context.bot, user_id, text if owners or admins else "📭 لا يوجد", parse_mode='HTML')

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
            bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
            if bot_member.status != 'administrator':
                await safe_send(
                    context.bot, user_id,
                    "❌ <b>البوت ليس مشرفاً في المجموعة!</b>\n\n"
                    "يجب ترقية البوت إلى مشرف أولاً:\n"
                    "1. افتح إعدادات المجموعة\n"
                    "2. اختر «المشرفون»\n"
                    "3. أضف البوت كمشرف\n"
                    "4. منحه صلاحية حذف الرسائل على الأقل",
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
            if not perms.get('can_pin_messages', False):
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
            CACHE.invalidate("has_sub", target_id)
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
            CACHE.invalidate("has_sub", user_id)
        elif days == -1:
            await safe_send(context.bot, user_id, await _trans('cannot_redeem_own', lang, "❌ لا يمكنك استخدام كودك الخاص"))
        else:
            await safe_send(context.bot, user_id, await _trans('gift_invalid', lang, "❌ كود غير صالح"))