#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_command.py - معالجات الأوامر (CommandHandlers) - v7.5.27
===================================================================================
🆕 v7.5.27 (MOOD IMPORT FIX):
    ✅ mood(): تصحيح مسار الاستيراد
       - كان: from handlers_message import analyze_sentiment  ❌
       - صار: from handlers.handlers_message import ...        ✅
       - مع fallback للتوافق مع أي هيكل قديم
       - النتيجة: /mood يعمل الآن

🆕 v7.5.26 (FIX /start STATE):
    ✅ start() يُصفِّر StateManager + user_data keys المعلقة
    ✅ حل مشكلة: /start بعد "تعيين قناة التحديثات" كان يبقي الحالة
       معلقة → الرسالة التالية تُفسَّر كإضافة قناة

🆕 v7.5.25 (DB-DIAGNOSTICS):
    ✅ db_diag: /db_diag — تشخيص شامل لقاعدة البيانات
    ✅ db_vacuum: /db_vacuum — تنظيف VACUUM ANALYZE

🆕 v7.5.24 (RENDER-READY):
    ✅ _trans: fallback آمن لكل المفاتيح
    ✅ HTML بدل Markdown في كل الرسائل
===================================================================================
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
    is_authorized_in_group,
    check_bot_permissions, invalidate_auth_cache, apply_penalty,
    get_text, StateManager, UserState,
    KeyboardFactory, TranslationManager, CB,
    export_auto_replies,
)
from cache import user_cache

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# ثوابت بوتات تليجرام الرسمية
# ═══════════════════════════════════════════════════════════════════

ANONYMOUS_BOT_ID = 1087968824   # GroupAnonymousBot
CHANNEL_BOT_ID = 136817688      # ChannelBot

# ═══════════════════════════════════════════════════════════════════
# ✅ v7.5.27: import دالة تحليل المشاعر مع fallback
# ═══════════════════════════════════════════════════════════════════
try:
    from handlers.handlers_message import analyze_sentiment
    _MOOD_AVAILABLE = True
except ImportError:
    try:
        from handlers_message import analyze_sentiment
        _MOOD_AVAILABLE = True
    except ImportError:
        analyze_sentiment = None
        _MOOD_AVAILABLE = False

# ═══════════════════════════════════════════════════════════════════
# ✅ v7.5.26: مفاتيح user_data المعلقة التي تُمسح عند /start
# ═══════════════════════════════════════════════════════════════════

_STALE_KEYS_ON_START = (
    'sec_chat', 'security_chat_id', 'adv_chat', 'auto_chat',
    'schedule_ch', 'ban_chat', 'contest_join', 'log_group_id',
    'pin_msg_id', 'channel_page', 'post_page', 'adm_ch_page',
    'adm_gr_page', 'auto_keyword', 'contest_id', 'contest_title',
    'contest_desc', 'contest_prize', 'last_cb_',
)


def _clear_stale_state(user_id: int, context) -> None:
    """
    ✅ v7.5.26: يمسح أي حالة معلقة عند /start.

    المشكلة المُصلَحة:
      المستخدم يضغط "تعيين قناة التحديثات" (WAIT_UPDATE_CH)
      → يرسل /start (لا يمسح الحالة)
      → يرسل @channel
      → handle_private يعالجها كـ WAIT_UPDATE_CH أو WAIT_CHANNEL

    هذا يُصلح بمسح الحالة عند كل /start.
    """
    try:
        StateManager.clear(user_id)
    except Exception as e:
        logger.debug(f"StateManager.clear({user_id}): {e}")

    try:
        for k in _STALE_KEYS_ON_START:
            try:
                context.user_data.pop(k, None)
            except Exception:
                pass
        # مسح إضافي لأي key يبدأ بـ last_cb_
        for k in list(context.user_data.keys()):
            if isinstance(k, str) and k.startswith('last_cb_'):
                context.user_data.pop(k, None)
    except Exception as e:
        logger.debug(f"_clear_stale_state user_data: {e}")


# ═══════════════════════════════════════════════════════════════════
# دوال مساعدة
# ═══════════════════════════════════════════════════════════════════

def _safe_mtime(p):
    try:
        return p.stat().st_mtime
    except (OSError, FileNotFoundError):
        return 0


def _get_field(row, key, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row.get(key, default)
    except AttributeError:
        pass
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return default


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except (TypeError, ValueError):
        return {}


def _mask_id(id_value, prefix=3, suffix=2):
    if id_value is None:
        return "***"
    s = str(id_value)
    if len(s) <= 5:
        return "***"
    if len(s) > prefix + suffix:
        return s[:prefix] + "***" + s[-suffix:]
    return s[:prefix] + "***"


def _is_anonymous_sender(update: Update) -> bool:
    if not update or not update.effective_user:
        return False
    return (
        update.effective_user.id == ANONYMOUS_BOT_ID
        and getattr(update.effective_user, 'is_bot', False)
    )


# ═══════════════════════════════════════════════════════════════════
# ✅ الترجمة الآمنة
# ═══════════════════════════════════════════════════════════════════

async def _trans(key: str, lang: str, default: str = "") -> str:
    """
    ✅ v7.5.24: ترجمة آمنة مع fallback عربي.
    """
    if not key:
        return default or ""

    # 1) من TranslationManager (locales/*.json)
    try:
        if lang and lang != 'off':
            text = TranslationManager.get_text(lang, key)
            if text and text != key:
                return text
    except Exception as e:
        logger.debug(f"_trans({key}, {lang}) TranslationManager: {e}")

    # 2) من get_text (قديم)
    try:
        if lang and lang != 'off':
            text = await get_text(lang, key)
            if text and text != key:
                return text
    except Exception as e:
        logger.debug(f"_trans({key}, {lang}) get_text: {e}")

    # 3) fallback
    return default or key


async def _get_lang(user_id: int) -> str:
    """جلب لغة المستخدم بأمان."""
    try:
        return await DB.get_user_language(user_id) or 'ar'
    except Exception:
        return 'ar'


# ═══════════════════════════════════════════════════════════════════
# حذف تلقائي للرسائل
# ═══════════════════════════════════════════════════════════════════

async def _delete_message_after(bot, chat_id: int, message_id: int, delay: int = 10):
    try:
        await asyncio.sleep(delay)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.debug(f"حذف تلقائي فشل: {e}")


async def _send_and_auto_delete(
    context, chat_id: int, text: str,
    reply_markup=None, parse_mode=None, delay: int = 10,
):
    try:
        msg = await context.bot.send_message(
            chat_id=chat_id, text=text,
            reply_markup=reply_markup, parse_mode=parse_mode,
        )
        asyncio.create_task(
            _delete_message_after(context.bot, chat_id, msg.message_id, delay)
        )
        return msg
    except BadRequest as e:
        err = str(e).lower()
        if "can't parse" in err or "parse" in err:
            try:
                msg = await context.bot.send_message(
                    chat_id=chat_id, text=text,
                    reply_markup=reply_markup, parse_mode=None,
                )
                asyncio.create_task(
                    _delete_message_after(context.bot, chat_id, msg.message_id, delay)
                )
                return msg
            except Exception as e2:
                logger.error(f"فشل إرسال (بدون parse): {e2}")
        logger.error(f"فشل إرسال+حذف: {e}")
        return None
    except Exception as e:
        logger.error(f"فشل إرسال+حذف: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════
# الرد في المكان الصحيح
# ═══════════════════════════════════════════════════════════════════

async def _safe_edit_or_send(update, context, text, reply_markup=None, parse_mode=None):
    query = update.callback_query
    chat = update.effective_chat if update else None
    if chat and chat.type in ('group', 'supergroup'):
        target = chat.id
    else:
        target = update.effective_user.id

    if query and query.message:
        try:
            await query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=parse_mode,
            )
            return True
        except BadRequest as e:
            err = str(e).lower()
            if "message is not modified" in err:
                return True
            if "can't parse" in err or "parse" in err:
                try:
                    await query.edit_message_text(
                        text, reply_markup=reply_markup, parse_mode=None
                    )
                    return True
                except Exception:
                    pass
            logger.debug(f"edit فشل، إرسال جديدة: {e}")
        except Exception as e:
            logger.debug(f"edit error: {e}")

    try:
        await context.bot.send_message(
            target, text, reply_markup=reply_markup, parse_mode=parse_mode,
        )
        return True
    except BadRequest as e:
        err = str(e).lower()
        if "can't parse" in err or "parse" in err:
            try:
                await context.bot.send_message(
                    target, text, reply_markup=reply_markup, parse_mode=None
                )
                return True
            except Exception:
                pass
        logger.error(f"فشل إرسال: {e}")
        return False
    except Exception as e:
        logger.error(f"فشل إرسال: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════
# كاش الاشتراك الإجباري
# ═══════════════════════════════════════════════════════════════════

_force_sub_cache: dict = {}
_FORCE_SUB_CACHE_TTL = 180
_force_channel_cache: dict = {}
_FORCE_CHANNEL_CACHE_TTL = 600


async def _get_force_channel_cached(bot, force_ch: str):
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
        if cached:
            return cached[1]
        return None


async def _check_force_subscription_cached(bot, user_id: int, force_ch: str) -> bool:
    now = _time_module.time()
    cache_key = (user_id, force_ch)
    cached = _force_sub_cache.get(cache_key)
    if cached:
        ts, is_subscribed = cached
        if now - ts < _FORCE_SUB_CACHE_TTL:
            return is_subscribed
    try:
        target = int(force_ch) if force_ch.lstrip('-').isdigit() else f"@{force_ch}"
        member = await bot.get_chat_member(target, user_id)
        is_subscribed = member.status in ('member', 'administrator', 'creator')
        _force_sub_cache[cache_key] = (now, is_subscribed)
        return is_subscribed
    except Exception as e:
        logger.debug(f"⚠️ get_chat_member فشل: {e}")
        return True


def _invalidate_force_sub_cache(user_id: int = None):
    if user_id is None:
        _force_sub_cache.clear()
        _force_channel_cache.clear()
    else:
        keys_to_del = [k for k in _force_sub_cache if k[0] == user_id]
        for k in keys_to_del:
            _force_sub_cache.pop(k, None)


# ═══════════════════════════════════════════════════════════════════
# CommandHandlers
# ═══════════════════════════════════════════════════════════════════

class CommandHandlers:

    # ═══════════════════════════════════════════════════════════════
    # ✅ v7.5.26: start — يمسح الحالة المعلقة أولاً
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        username = update.effective_user.username or ""
        first_name = update.effective_user.first_name or ""

        # ✅ v7.5.26: امسح أي حالة معلقة من عمليات سابقة
        _clear_stale_state(user_id, context)

        try:
            user_exists = await DB.fetchval(
                "SELECT 1 FROM users WHERE user_id = ?", (user_id,)
            )
            if not user_exists:
                await DB.register_user(user_id, username, first_name)
        except Exception as e:
            logger.warning(f"register_user check failed: {e}")
            try:
                await DB.register_user(user_id, username, first_name)
            except Exception:
                pass

        args = context.args or []
        if args and args[0].startswith('ref_'):
            ref_code = args[0][4:]
            referrer = await DB.get_user_by_referral_code(ref_code)
            if referrer and referrer != user_id and not await DB.is_user_banned(referrer):
                existing = await DB.fetchone(
                    "SELECT 1 FROM referrals WHERE referred_id=?", (user_id,)
                )
                if not existing:
                    if await DB.add_referral(referrer, user_id):
                        reward = await DB.get_referral_stats(referrer)
                        try:
                            ref_lang = await _get_lang(referrer)
                            ref_msg = await _trans(
                                'referral_notification', ref_lang,
                                "🎁 تمت إحالة {referred}. لديك {available} يوم متاح للصرف."
                            )
                            ref_msg = ref_msg.format(
                                referred=f"`{_mask_id(user_id)}`",
                                available=reward.get('available', 0)
                            )
                            await context.bot.send_message(referrer, ref_msg)
                        except Exception as e:
                            logger.warning(f"⚠️ فشل إرسال إشعار الإحالة: {e}")

        force_ch = await DB.get_force_subscribe_channel()
        if force_ch and user_id != CONFIG.PRIMARY_OWNER_ID:
            try:
                is_subscribed = await _check_force_subscription_cached(
                    context.bot, user_id, force_ch
                )
                if not is_subscribed:
                    chat = await _get_force_channel_cached(context.bot, force_ch)
                    invite_link = None
                    if chat:
                        try:
                            invite_link = await context.bot.export_chat_invite_link(chat.id)
                        except Exception:
                            pass

                    lang = await _get_lang(user_id)
                    subscribe_text = await _trans('subscribe_btn', lang, "📢 اشترك")
                    check_text = await _trans('check_sub_btn', lang, "✅ تحقق")

                    if invite_link:
                        kb = InlineKeyboardMarkup([[
                            InlineKeyboardButton(subscribe_text, url=invite_link),
                            InlineKeyboardButton(check_text, callback_data=CB.CHECK_SUB)
                        ]])
                    else:
                        kb = InlineKeyboardMarkup([[
                            InlineKeyboardButton(check_text, callback_data=CB.CHECK_SUB)
                        ]])

                    force_msg = await _trans(
                        'force_sub_message', lang,
                        "⚠️ اشترك في القناة أولاً"
                    )
                    await _safe_edit_or_send(
                        update, context, force_msg,
                        reply_markup=kb, parse_mode=None,
                    )
                    return
            except Exception as e:
                logger.error(f"❌ خطأ في التحقق من الاشتراك الإجباري: {e}")

        user_data = await user_cache.get_or_load(user_id, DB)
        lang = user_data.get('language', 'ar') or 'ar'
        channel_info = user_data.get('channel_info')
        unpublished_posts = user_data.get('unpublished_posts', 0)
        groups_count = user_data.get('groups_count', 0)
        has_sub = user_data.get('has_subscription', False)
        auto = user_data.get('auto_publish', True)
        recycle = user_data.get('auto_recycle', True)

        ch_display = await _trans('no_active_channel', lang, "لا توجد قنوات")
        if channel_info and isinstance(channel_info, dict):
            ch_name = channel_info.get('channel_name')
            if ch_name:
                ch_display = ch_name

        sub_text = await _trans('subscription_active', lang, "✅ مفعل") if has_sub \
            else await _trans('subscription_inactive', lang, "❌ غير مفعل")
        auto_text = await _trans('enabled', lang, "مفعل") if auto \
            else await _trans('disabled', lang, "معطل")
        recycle_text = await _trans('enabled', lang, "مفعل") if recycle \
            else await _trans('disabled', lang, "معطل")

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
            lang, 'main_menu',
            user_name=f"<code>{user_id}</code>",
            groups_count=groups_count,
            active_channel=ch_display,
            unpublished_posts=unpublished_posts,
            auto_publish=auto_text,
            auto_recycle=recycle_text,
            subscription_status=sub_text
        )
        await _safe_edit_or_send(update, context, title, reply_markup=kb, parse_mode='HTML')

    @staticmethod
    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        help_text = await _trans('help_text', lang, "❓ المساعدة")
        await _safe_edit_or_send(update, context, help_text, parse_mode=None)

    @staticmethod
    async def trial(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)

        if await DB.has_used_trial(user_id):
            await _safe_edit_or_send(
                update, context,
                await _trans('trial_used', lang, "❌ لقد استخدمت التجربة المجانية بالفعل."),
                parse_mode=None,
            )
            return

        days = await DB.activate_trial(user_id)
        if days > 0:
            msg = await _trans('trial_activated', lang,
                               "✅ تم تفعيل التجربة المجانية لمدة {days} يوم")
            try:
                msg = msg.format(days=days)
            except (KeyError, IndexError):
                pass
        else:
            msg = await _trans('trial_failed', lang, "❌ تعذر تفعيل التجربة")

        try:
            await DB.invalidate_subscription_cache(user_id)
        except Exception as e:
            logger.warning(f"⚠️ invalidate_subscription_cache: {e}")
        try:
            await user_cache.invalidate(user_id)
        except Exception:
            pass

        await _safe_edit_or_send(update, context, msg, parse_mode=None)

    @staticmethod
    async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        kb = KeyboardFactory.build("plans", lang=lang)
        await _safe_edit_or_send(
            update, context,
            await _trans('plan_selector', lang, "💎 اختر باقة:"),
            reply_markup=kb, parse_mode=None,
        )

    @staticmethod
    async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        kb = KeyboardFactory.build("support", lang=lang)
        await _safe_edit_or_send(
            update, context,
            await _trans('send_support_message', lang, "📞 أرسل رسالة الدعم"),
            reply_markup=kb, parse_mode=None,
        )

    # ═══════════════════════════════════════════════════════════════════
    # developer — مترجم
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    async def developer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)

        dev_name = getattr(CONFIG, 'DEVELOPER_NAME', "Relax") or "Relax"
        dev_contact = getattr(CONFIG, 'DEVELOPER_CONTACT', "@RelaxMggr") or "@RelaxMggr"
        if "Reelaaax" in dev_contact or "Reelaaaxbot" in dev_contact:
            dev_contact = "@RelaxMggr"
        if not dev_name or dev_name == "developer_info":
            dev_name = "Relax"

        title = await _trans('dev_info_title', lang, "معلومات المطور")
        name_label = await _trans('dev_name_label', lang, "الاسم")
        contact_label = await _trans('dev_contact_label', lang, "التواصل")
        bot_label = await _trans('dev_bot_label', lang, "البوت")
        home_label = await _trans('main', lang, "🏠 القائمة الرئيسية")

        text = (
            f"👨‍💻 <b>{title}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"👤 <b>{name_label}:</b> {escape(str(dev_name))}\n"
            f"📞 <b>{contact_label}:</b> {escape(str(dev_contact))}\n"
            f"━━━━━━━━━━━━━━━\n\n"
            f"💡 <b>{bot_label}:</b> @{CONFIG.BOT_USERNAME}"
        )

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(home_label, callback_data=CB.MAIN)
        ]])

        await _safe_edit_or_send(update, context, text, reply_markup=kb, parse_mode='HTML')

    @staticmethod
    async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not CONFIG.is_developer(user_id):
            await _safe_edit_or_send(
                update, context, await _trans('unauthorized', lang, "❌ غير مصرح"),
                parse_mode=None,
            )
            return
        try:
            stats_data = await DB.get_bot_stats()
            if not isinstance(stats_data, dict):
                stats_data = {}
        except Exception as e:
            logger.warning(f"get_bot_stats failed: {e}")
            stats_data = {}

        text = await _trans('stats_message', lang,
            "📊 <b>الإحصائيات</b>\n\n👥 المستخدمون: {users}\n"
            "📡 القنوات: {channels}\n👥 المجموعات: {groups}\n"
            "📝 المنشورات: {posts}\n✅ المنشورة: {published}\n"
            "💎 الاشتراكات النشطة: {active_subs}\n🎫 التذاكر: {tickets}"
        )
        try:
            text = text.format(
                users=stats_data.get('users', 0),
                channels=stats_data.get('channels', 0),
                groups=stats_data.get('groups', 0),
                posts=stats_data.get('posts', 0),
                published=stats_data.get('published', 0),
                active_subs=stats_data.get('active_subs', 0),
                tickets=stats_data.get('tickets', 0),
            )
        except (KeyError, IndexError):
            pass
        await _safe_edit_or_send(update, context, text, parse_mode='HTML')

    @staticmethod
    async def language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
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
        await _safe_edit_or_send(
            update, context, f"{choose_lang}\n\n{current_lang}: {lang}",
            reply_markup=kb, parse_mode=None,
        )

    @staticmethod
    async def replies_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        await _safe_edit_or_send(
            update, context,
            await _trans('replies_work', lang, "📚 الردود التلقائية تعمل!"),
            parse_mode=None,
        )

    @staticmethod
    async def contests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        contests = await DB.get_active_contests(10)
        if not contests:
            await _safe_edit_or_send(
                update, context,
                await _trans('no_contests', lang, "📭 لا توجد مسابقات نشطة"),
                parse_mode=None,
            )
            return

        active_label = await _trans('active_contests', lang, "المسابقات النشطة")
        participants_label = await _trans('participants', lang, "المشاركون")
        join_text = await _trans('join_contest', lang, "✍️ المشاركة")

        text = f"🏆 <b>{active_label}</b>\n\n"
        kb = []
        for c in contests:
            c_d = _row_to_dict(c)
            end_date = c_d.get('end_date') or ''
            title = escape(str(c_d.get('title', '')))
            prize = escape(str(c_d.get('prize', '')))
            participants = c_d.get('participants', 0)
            c_id = c_d.get('id')
            if c_id is None:
                continue
            text += (
                f"• <b>{title}</b>\n"
                f"  🎁 {prize}\n"
                f"  📅 {escape(str(end_date)[:10])}\n"
                f"  👥 {participants_label}: {participants}\n\n"
            )
            kb.append([InlineKeyboardButton(
                f"{join_text} {title[:20]}",
                callback_data=f"{CB.CONTEST_JOIN}:{c_id}"
            )])
        kb.append([InlineKeyboardButton(
            KeyboardFactory.get_text("back", lang), callback_data=CB.BACK
        )])
        await _safe_edit_or_send(
            update, context, text,
            reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML'
        )

    # ═══════════════════════════════════════════════════════════════════
    # ✅ v7.5.27: mood — إصلاح مسار import
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    async def mood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        args = context.args or []

        if not args:
            StateManager.set(user_id, UserState.WAIT_MOOD)
            await _safe_edit_or_send(
                update, context,
                await _trans('send_mood_text', lang, "📝 أرسل النص:"),
                parse_mode=None,
            )
            return

        text = " ".join(args)

        # ✅ v7.5.27: analyze_sentiment محمّلة على مستوى module
        if analyze_sentiment is None:
            await _safe_edit_or_send(
                update, context,
                await _trans('mood_unavailable', lang,
                             "❌ خدمة تحليل المشاعر غير متاحة"),
                parse_mode=None,
            )
            return

        try:
            result = analyze_sentiment(text)
        except Exception as e:
            logger.error(f"analyze_sentiment فشل: {e}", exc_info=True)
            await _safe_edit_or_send(
                update, context,
                await _trans('mood_unavailable', lang,
                             "❌ خدمة تحليل المشاعر غير متاحة"),
                parse_mode=None,
            )
            return

        if not isinstance(result, dict):
            await _safe_edit_or_send(
                update, context,
                await _trans('mood_unavailable', lang,
                             "❌ خدمة تحليل المشاعر غير متاحة"),
                parse_mode=None,
            )
            return

        mood_analysis = await _trans('mood_analysis', lang, 'تحليل المشاعر')
        mood_text_l = await _trans('mood_text', lang, 'النص')
        mood_result = await _trans('mood_result', lang, 'النتيجة')
        mood_positive = await _trans('mood_positive', lang, 'إيجابي')
        mood_negative = await _trans('mood_negative', lang, 'سلبي')
        mood_words = await _trans('mood_words', lang, 'الكلمات')

        response = (
            f"{result.get('emoji', '🎭')} <b>{mood_analysis}</b>\n\n"
            f"📝 {mood_text_l}: <code>{escape(text[:100])}</code>\n"
            f"🎯 {mood_result}: <b>{escape(str(result.get('sentiment', '?')))}</b>\n\n"
            f"😊 {mood_positive}: {result.get('positive_percent', 0):.0f}%\n"
            f"😔 {mood_negative}: {result.get('negative_percent', 0):.0f}%\n"
            f"📊 {mood_words}: {result.get('total_words', 0)}"
        )
        await _safe_edit_or_send(update, context, response, parse_mode='HTML')

    @staticmethod
    async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not CONFIG.is_developer(user_id):
            await _safe_edit_or_send(
                update, context, await _trans('unauthorized', lang, "❌ غير مصرح"),
                parse_mode=None,
            )
            return
        admin_btn = await _trans('admin_panel_btn', lang, "👑 لوحة الأدمن")
        open_text = await _trans('open_admin_panel', lang,
                                 "👑 لوحة الأدمن\n\nاضغط الزر أدناه:")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(admin_btn, callback_data=CB.ADMIN)
        ]])
        await _safe_edit_or_send(
            update, context, open_text,
            reply_markup=kb, parse_mode='HTML',
        )

    @staticmethod
    async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not CONFIG.is_developer(user_id):
            await _safe_edit_or_send(
                update, context, await _trans('unauthorized', lang, "❌ غير مصرح"),
                parse_mode=None,
            )
            return
        StateManager.set(user_id, UserState.WAIT_BROADCAST)
        await _safe_edit_or_send(
            update, context,
            await _trans('send_broadcast', lang, "📨 أرسل الرسالة التي تريد بثها:"),
            parse_mode=None,
        )

    @staticmethod
    async def set_force(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not CONFIG.is_developer(user_id):
            return
        StateManager.set(user_id, UserState.WAIT_FORCE)
        await _safe_edit_or_send(
            update, context,
            await _trans('send_force_ch_prompt', lang, "🔒 أرسل معرف القناة:"),
            parse_mode=None,
        )

    @staticmethod
    async def set_update_ch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not CONFIG.is_developer(user_id):
            return
        StateManager.set(user_id, UserState.WAIT_UPDATE_CH)
        await _safe_edit_or_send(
            update, context,
            await _trans('send_update_ch_prompt', lang, "📢 أرسل معرف قناة التحديثات:"),
            parse_mode=None,
        )

    @staticmethod
    async def set_log_ch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not CONFIG.is_developer(user_id):
            return
        StateManager.set(user_id, UserState.WAIT_LOG_CH)
        await _safe_edit_or_send(
            update, context,
            await _trans('send_log_ch_prompt', lang, "📋 أرسل معرف قناة السجلات:"),
            parse_mode=None,
        )

    @staticmethod
    async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        ⚠️ ملاحظة v5.5.0:
        هذا المعالج يضبط الحالة فقط. العملية الفعلية (إضافة الأدمن إلى DB)
        تحدث في handlers_message.py → handle_private → WAIT_ADMIN_ADD.
        استدعاء refresh_admin_commands يتم هناك بعد نجاح الإضافة.
        """
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not CONFIG.is_developer(user_id):
            return
        StateManager.set(user_id, UserState.WAIT_ADMIN_ADD)
        await _safe_edit_or_send(
            update, context,
            await _trans('add_admin_prompt', lang, "👑 أرسل معرف المشرف:"),
            parse_mode=None,
        )

    @staticmethod
    async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        ⚠️ ملاحظة v5.5.0:
        نفس ما ورد في add_admin — العملية الفعلية في handlers_message.py.
        """
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not CONFIG.is_developer(user_id):
            return
        StateManager.set(user_id, UserState.WAIT_ADMIN_REM)
        await _safe_edit_or_send(
            update, context,
            await _trans('remove_admin_prompt', lang, "🗑️ أرسل معرف المشرف:"),
            parse_mode=None,
        )

    @staticmethod
    async def export_replies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not CONFIG.is_developer(user_id):
            return
        try:
            count = await export_auto_replies(-1)
        except Exception as e:
            logger.error(f"export_replies: {e}")
            count = 0
        msg = await _trans('export_success', lang, "✅ تم تصدير {count} رد")
        try:
            msg = msg.format(count=count)
        except (KeyError, IndexError):
            pass
        await _safe_edit_or_send(update, context, msg, parse_mode=None)

    @staticmethod
    async def import_replies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not CONFIG.is_developer(user_id):
            return
        StateManager.set(user_id, UserState.WAIT_IMPORT_FILE)
        await _safe_edit_or_send(
            update, context,
            await _trans('send_json_prompt', lang, "📤 أرسل ملف JSON:"),
            parse_mode=None,
        )

    @staticmethod
    async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not CONFIG.is_developer(user_id):
            return
        await _safe_edit_or_send(
            update, context,
            await _trans('backup_start', lang, "⏳ جارٍ النسخ الاحتياطي..."),
            parse_mode=None,
        )
        try:
            from utils import BackgroundTasks
            asyncio.create_task(BackgroundTasks._do_backup())
            await _safe_edit_or_send(
                update, context,
                await _trans('backup_done', lang, "✅ تم أخذ نسخة احتياطية"),
                parse_mode=None,
            )
        except Exception as e:
            await _safe_edit_or_send(
                update, context, f"❌ {str(e)[:50]}",
                parse_mode=None,
            )

    @staticmethod
    async def restore(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not CONFIG.is_developer(user_id):
            return
        try:
            backups = sorted(PATHS.BACKUPS.glob("backup_*.db"),
                             key=_safe_mtime, reverse=True)
            if not backups:
                await _safe_edit_or_send(
                    update, context,
                    await _trans('no_backups_full', lang, "📭 لا توجد نسخ"),
                    parse_mode=None,
                )
                return
            back_label = KeyboardFactory.get_text("back", lang)
            kb = []
            for b in backups[:10]:
                fname = b.name
                kb.append([InlineKeyboardButton(
                    f"📁 {fname}",
                    callback_data=f"admin_restore_file:{fname}"
                )])
            kb.append([InlineKeyboardButton(back_label, callback_data=CB.ADMIN)])
            await _safe_edit_or_send(
                update, context,
                await _trans('choose_backup_restore_btn', lang,
                             "📂 اختر نسخة احتياطية للاستعادة:"),
                reply_markup=InlineKeyboardMarkup(kb), parse_mode=None,
            )
        except Exception as e:
            logger.error(f"restore: {e}", exc_info=True)
            await _safe_edit_or_send(
                update, context,
                await _trans('error_occurred', lang, "❌ حدث خطأ"),
                parse_mode=None,
            )

    @staticmethod
    async def auto_publish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        cur = await DB.get_auto_publish_status(user_id)
        await DB.set_auto_publish(user_id, not cur)
        status = await _trans('enabled', lang, "مفعل") if not cur \
            else await _trans('disabled', lang, "معطل")
        msg = await _trans('auto_publish_toggle', lang, "✅ النشر التلقائي: {status}")
        try:
            msg = msg.format(status=status)
        except (KeyError, IndexError):
            pass
        await _safe_edit_or_send(update, context, msg, parse_mode=None)
        await user_cache.invalidate(user_id)

    @staticmethod
    async def auto_recycle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        cur = await DB.get_auto_recycle_status(user_id)
        await DB.set_auto_recycle(user_id, not cur)
        status = await _trans('enabled', lang, "مفعل") if not cur \
            else await _trans('disabled', lang, "معطل")
        msg = await _trans('auto_recycle_toggle', lang, "✅ التدوير التلقائي: {status}")
        try:
            msg = msg.format(status=status)
        except (KeyError, IndexError):
            pass
        await _safe_edit_or_send(update, context, msg, parse_mode=None)
        await user_cache.invalidate(user_id)

    @staticmethod
    async def channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        channels = await DB.get_user_channels(user_id)
        if not channels:
            await _safe_edit_or_send(
                update, context,
                await _trans('no_channels', lang, "📭 لا توجد قنوات"),
                parse_mode=None,
            )
            return
        title = await _trans('your_channels', lang, "📡 قنواتك:")
        text = f"{title}\n\n"
        for ch in channels:
            ch_d = _row_to_dict(ch)
            name = _get_field(ch_d, 'channel_name', '?')
            ch_id = _get_field(ch_d, 'channel_id', '?')
            text += f"• {escape(str(name))} (<code>{escape(str(ch_id))}</code>)\n"
        await _safe_edit_or_send(update, context, text, parse_mode='HTML')

    @staticmethod
    async def posts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        active = await DB.get_active_channel(user_id)
        if not active:
            await _safe_edit_or_send(
                update, context,
                await _trans('no_active_channel', lang, "❌ لا توجد قناة نشطة"),
                parse_mode=None,
            )
            return
        posts = await DB.get_user_posts(user_id, active, 10)
        if not posts:
            await _safe_edit_or_send(
                update, context,
                await _trans('no_posts', lang, "📭 لا توجد منشورات"),
                parse_mode=None,
            )
            return
        title = await _trans('your_posts', lang, "📋 منشوراتك:")
        text = f"{title}\n\n"
        for p in posts:
            p_d = _row_to_dict(p)
            pid = _get_field(p_d, 'id', '?')
            ptext = _get_field(p_d, 'text', '') or ''
            text += f"• <code>{escape(str(pid))}</code>: {escape(str(ptext)[:30])}\n"
        await _safe_edit_or_send(update, context, text, parse_mode='HTML')

    # ═══════════════════════════════════════════════════════════════
    # أوامر المجموعات
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def security(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or update.effective_chat.type not in ['group', 'supergroup']:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await _safe_edit_or_send(
                update, context,
                await _trans('unauthorized', lang, "❌ غير مصرح"),
                parse_mode=None,
            )
            return
        context.user_data['security_chat_id'] = chat_id
        settings = await DB.get_security_settings(chat_id)
        if not isinstance(settings, dict):
            settings = _row_to_dict(settings)
        try:
            text = KeyboardFactory._format_security_text(settings, {}, lang=lang)
        except TypeError:
            text = KeyboardFactory._format_security_text(settings)
        kb = KeyboardFactory.build("security", chat_id=chat_id, lang=lang)
        await _safe_edit_or_send(update, context, text,
                                 reply_markup=kb, parse_mode='HTML')

    @staticmethod
    async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or update.effective_chat.type not in ['group', 'supergroup']:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await _safe_edit_or_send(
                update, context,
                await _trans('unauthorized', lang, "❌ غير مصرح"),
                parse_mode=None,
            )
            return
        kb = KeyboardFactory.build("panel", chat_id=chat_id, lang=lang)
        await _safe_edit_or_send(
            update, context,
            await _trans('group_panel', lang, "📋 لوحة تحكم المجموعة"),
            reply_markup=kb, parse_mode=None,
        )

    @staticmethod
    async def lock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or update.effective_chat.type not in ['group', 'supergroup']:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            return
        await DB.execute(
            "INSERT OR REPLACE INTO chat_locks "
            "(chat_id, locked, locked_at, locked_by) VALUES (?,1,?,?)",
            (chat_id, TimeUtils.sql_iso(), user_id),
        )
        await _safe_edit_or_send(
            update, context,
            await _trans('group_locked_full', lang, "🔒 تم القفل"),
            parse_mode=None,
        )

    @staticmethod
    async def unlock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or update.effective_chat.type not in ['group', 'supergroup']:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            return
        await DB.execute("DELETE FROM chat_locks WHERE chat_id=?", (chat_id,))
        await _safe_edit_or_send(
            update, context,
            await _trans('group_unlocked_full', lang, "🔓 تم الفتح"),
            parse_mode=None,
        )

    @staticmethod
    async def register_hidden_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if user_id != CONFIG.PRIMARY_OWNER_ID:
            return
        if not context.args:
            await _safe_edit_or_send(update, context,
                                     "📝 /register_hidden_owner <user_id>",
                                     parse_mode=None)
            return
        try:
            owner_id = int(context.args[0])
            if owner_id <= 0:
                raise ValueError
        except (ValueError, TypeError):
            await _safe_edit_or_send(update, context,
                                     "⚠️ معرف غير صالح", parse_mode=None)
            return
        chat_id = update.effective_chat.id
        await DB.execute(
            "INSERT OR IGNORE INTO hidden_owner_groups "
            "(chat_id, owner_id, is_hidden) VALUES (?,?,1)",
            (chat_id, owner_id),
        )
        invalidate_auth_cache(chat_id, owner_id)
        await _safe_edit_or_send(
            update, context,
            f"✅ تم تسجيل <code>{owner_id}</code> كمالك مخفي",
            parse_mode='HTML',
        )

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
        await DB.execute("DELETE FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?",
                         (chat_id, owner_id))
        invalidate_auth_cache(chat_id, owner_id)
        await _safe_edit_or_send(update, context,
                                 f"✅ تم إزالة <code>{owner_id}</code>",
                                 parse_mode='HTML')

    @staticmethod
    async def add_hidden_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        is_owner = user_id == CONFIG.PRIMARY_OWNER_ID
        if not is_owner:
            row = await DB.fetchone(
                "SELECT 1 FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?",
                (chat_id, user_id))
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
        await _safe_edit_or_send(
            update, context,
            f"✅ تم إضافة <code>{admin_id}</code> كمشرف مخفي",
            parse_mode='HTML',
        )

    @staticmethod
    async def remove_hidden_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        is_owner = user_id == CONFIG.PRIMARY_OWNER_ID
        if not is_owner:
            row = await DB.fetchone(
                "SELECT 1 FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?",
                (chat_id, user_id))
            is_owner = row is not None
        if not is_owner:
            return
        if not context.args:
            return
        try:
            admin_id = int(context.args[0])
        except (ValueError, TypeError):
            return
        await DB.execute("DELETE FROM hidden_admins WHERE chat_id=? AND admin_id=?",
                         (chat_id, admin_id))
        invalidate_auth_cache(chat_id, admin_id)
        await _safe_edit_or_send(update, context,
                                 f"✅ تم إزالة <code>{admin_id}</code>",
                                 parse_mode='HTML')

    @staticmethod
    async def list_hidden_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        is_owner = user_id == CONFIG.PRIMARY_OWNER_ID
        if not is_owner:
            row = await DB.fetchone(
                "SELECT 1 FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?",
                (chat_id, user_id))
            is_owner = row is not None
        if not is_owner:
            return
        owners = await DB.fetchall(
            "SELECT owner_id FROM hidden_owner_groups WHERE chat_id=?", (chat_id,))
        admins = await DB.fetchall(
            "SELECT admin_id FROM hidden_admins WHERE chat_id=?", (chat_id,))
        anonymous_admins = await DB.fetchall(
            "SELECT anonymous_id, user_id FROM anonymous_admins WHERE chat_id=?",
            (chat_id,)
        )
        text = "👤 <b>المخفيون</b>\n"
        for o in owners:
            o_d = _row_to_dict(o)
            text += f"👑 <code>{o_d.get('owner_id', '?')}</code>\n"
        for a in admins:
            a_d = _row_to_dict(a)
            text += f"🛡️ <code>{a_d.get('admin_id', '?')}</code>\n"
        for a in anonymous_admins:
            a_d = _row_to_dict(a)
            anon_id = a_d.get('anonymous_id')
            if anon_id in (ANONYMOUS_BOT_ID, CHANNEL_BOT_ID):
                continue
            real = f"<code>{a_d.get('user_id')}</code>" if a_d.get('user_id') else "غير معروف"
            text += f"🕵️ مجهول: <code>{anon_id or '?'}</code> (حقيقي: {real})\n"
        if not (owners or admins or anonymous_admins):
            text = "📭 لا يوجد"
        await _safe_edit_or_send(update, context, text, parse_mode='HTML')

    @staticmethod
    async def syncgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or update.effective_chat.type not in ['group', 'supergroup']:
            return

        chat_id = update.effective_chat.id
        chat_name = update.effective_chat.title or "بدون اسم"
        user_id = update.effective_user.id
        is_anon = _is_anonymous_sender(update)

        try:
            perms = await check_bot_permissions(context.bot, chat_id)
            if not perms['can_act']:
                await _safe_edit_or_send(
                    update, context,
                    "❌ <b>البوت لا يملك الصلاحيات الكافية!</b>\n\n"
                    "يجب أن يكون البوت مشرفاً مع صلاحية حذف الرسائل وتقييد الأعضاء.",
                    parse_mode='HTML',
                )
                return
        except Exception as e:
            await _safe_edit_or_send(update, context, f"❌ {escape(str(e)[:50])}",
                                     parse_mode=None)
            return

        try:
            all_admins = await context.bot.get_chat_administrators(chat_id)
        except Exception:
            await _safe_edit_or_send(update, context, "❌ فشل جلب المشرفين",
                                     parse_mode=None)
            return

        creator_id = None
        for admin in all_admins:
            if admin.status == 'creator' and not admin.user.is_bot:
                creator_id = admin.user.id
                break

        is_admin = False
        real_user_id = user_id

        if (update.message and update.message.sender_chat
                and update.message.sender_chat.id == chat_id):
            is_admin = True
            real_user_id = creator_id if creator_id else user_id
        elif is_anon:
            is_admin = True
            real_user_id = creator_id if creator_id else user_id
        else:
            for admin in all_admins:
                if admin.user.id == user_id:
                    is_admin = True
                    real_user_id = admin.user.id
                    break

        if not is_admin:
            await _safe_edit_or_send(
                update, context,
                "❌ <b>أنت لست مشرفاً في هذه المجموعة!</b>",
                parse_mode='HTML',
            )
            return

        try:
            await DB.register_group(
                chat_id, chat_name, creator_id or real_user_id,
                update.effective_chat.username,
            )
        except Exception:
            await _safe_edit_or_send(update, context, "❌ فشل تسجيل المجموعة",
                                     parse_mode=None)
            return

        try:
            if creator_id:
                await DB.execute(
                    "INSERT OR REPLACE INTO hidden_owner_groups "
                    "(chat_id, owner_id, is_hidden) VALUES (?,?,0)",
                    (chat_id, creator_id),
                )
                await DB.execute(
                    "INSERT OR IGNORE INTO user_groups_link (user_id, chat_id) VALUES (?,?)",
                    (creator_id, chat_id),
                )
                invalidate_auth_cache(chat_id, creator_id)

            if real_user_id and real_user_id > 0:
                await DB.execute(
                    "INSERT OR IGNORE INTO user_groups_link (user_id, chat_id) VALUES (?,?)",
                    (real_user_id, chat_id),
                )
                invalidate_auth_cache(chat_id, real_user_id)
        except Exception as e:
            logger.error(f"❌ فشل ربط المستخدم: {e}")

        try:
            admin_ids = [
                a.user.id for a in all_admins
                if a.user and not a.user.is_bot and a.user.id != chat_id
            ]
            admin_count = await DB.sync_group_admins(chat_id, admin_ids)
        except Exception:
            admin_count = 0

        anonymous_ids = []
        user_id_map = {}
        for admin in all_admins:
            if admin.user.is_bot and admin.status == 'administrator':
                anon_id = admin.user.id
                if anon_id in (ANONYMOUS_BOT_ID, CHANNEL_BOT_ID):
                    continue
                anonymous_ids.append(anon_id)
                row = await DB.fetchone(
                    "SELECT user_id FROM anonymous_admins "
                    "WHERE chat_id=? AND anonymous_id=?",
                    (chat_id, anon_id),
                )
                if row:
                    row_d = _row_to_dict(row)
                    if row_d.get('user_id'):
                        user_id_map[anon_id] = row_d['user_id']

        if anonymous_ids:
            try:
                await DB.sync_anonymous_admins(
                    chat_id, anonymous_ids,
                    added_by=real_user_id, user_id_map=user_id_map,
                )
                for anon_id, real_id in user_id_map.items():
                    if real_id and real_id > 0:
                        await DB.execute(
                            "INSERT OR IGNORE INTO user_groups_link "
                            "(user_id, chat_id) VALUES (?,?)",
                            (real_id, chat_id),
                        )
            except Exception as e:
                logger.error(f"❌ فشل sync_anonymous_admins: {e}")

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

        await _send_and_auto_delete(
            context, chat_id=chat_id, text=msg, parse_mode='HTML', delay=10,
        )

    # ═══════════════════════════════════════════════════════════════
    # أوامر الإشراف
    # ═══════════════════════════════════════════════════════════════

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
        if not update.effective_chat or update.effective_chat.type not in ['group', 'supergroup']:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            return
        if update.message and update.message.reply_to_message:
            perms = await check_bot_permissions(context.bot, chat_id)
            if not perms.get('can_pin', False):
                await _safe_edit_or_send(
                    update, context,
                    "❌ البوت لا يملك صلاحية تثبيت الرسائل.",
                    parse_mode=None,
                )
                return
            try:
                await context.bot.pin_chat_message(
                    chat_id, update.message.reply_to_message.message_id)
                await _safe_edit_or_send(update, context,
                                         "📌 تم التثبيت", parse_mode=None)
            except Exception as e:
                logger.error(f"❌ فشل التثبيت: {e}")

    @staticmethod
    async def _moderation_command(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                   action: str) -> None:
        if not update.effective_chat or update.effective_chat.type not in ['group', 'supergroup']:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await _safe_edit_or_send(
                update, context,
                await _trans('unauthorized', lang, "❌ غير مصرح"),
                parse_mode=None,
            )
            return
        perms = await check_bot_permissions(context.bot, chat_id)
        if not perms.get('can_act', False):
            await _safe_edit_or_send(
                update, context,
                "❌ البوت لا يملك الصلاحيات الكافية.",
                parse_mode=None,
            )
            return
        args = context.args or []
        if not args:
            usage = await _trans('moderation_usage', lang,
                                 "📝 /{action} معرف_المستخدم [مدة_بالدقائق]")
            try:
                usage = usage.replace("{action}", action)
            except Exception:
                pass
            await _safe_edit_or_send(update, context, usage, parse_mode=None)
            return
        try:
            target = int(args[0])
            if target <= 0:
                raise ValueError
        except (ValueError, TypeError):
            await _safe_edit_or_send(
                update, context,
                await _trans('invalid_id', lang, "❌ معرف غير صالح"),
                parse_mode=None,
            )
            return
        if await is_authorized_in_group(context.bot, chat_id, target):
            await _safe_edit_or_send(
                update, context,
                await _trans('cant_moderate_admin', lang, "❌ لا يمكن معاملة مشرف"),
                parse_mode=None,
            )
            return

        default_durations = {'ban': 0, 'mute': 3600, 'restrict': 1800,
                             'warn': 0, 'kick': 0}
        duration_seconds = default_durations.get(action, 60)
        reason_parts = []
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
                await _safe_edit_or_send(
                    update, context,
                    await _trans('unbanned_success', lang, "✅ تم إلغاء الحظر"),
                    parse_mode=None,
                )
            except Exception as e:
                await _safe_edit_or_send(
                    update, context, f"❌ {escape(str(e)[:50])}",
                    parse_mode=None,
                )
            return

        # ✅ v7.9.8: تمرير lang لـ apply_penalty
        success, msg = await apply_penalty(
            context.bot, chat_id, target, action,
            duration_seconds, reason, user_id,
            lang=lang,
        )
        await _safe_edit_or_send(update, context, msg, parse_mode='HTML')
        if success:
            try:
                await invalidate_auth_cache(chat_id=chat_id, user_id=target)
            except Exception:
                pass

    # ═══════════════════════════════════════════════════════════════
    # أوامر المطور
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def set_min_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not CONFIG.is_developer(user_id):
            await _safe_edit_or_send(
                update, context,
                await _trans('unauthorized', lang, "❌ غير مصرح"),
                parse_mode=None,
            )
            return
        args = context.args or []
        if not args:
            await _safe_edit_or_send(
                update, context,
                "📝 /set_min_interval <دقائق>",
                parse_mode=None,
            )
            return
        try:
            val = int(args[0])
            if val < 1:
                await _safe_edit_or_send(
                    update, context,
                    "❌ الحد الأدنى يجب أن يكون 1 دقيقة",
                    parse_mode=None,
                )
                return
            await DB.set_setting('min_publish_interval', str(val))
            await _safe_edit_or_send(
                update, context,
                f"✅ تم تعيين الحد الأدنى إلى {val} دقيقة",
                parse_mode=None,
            )
        except ValueError:
            await _safe_edit_or_send(update, context,
                                     "❌ قيمة غير صالحة", parse_mode=None)

    @staticmethod
    async def grant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not CONFIG.is_developer(user_id):
            await _safe_edit_or_send(
                update, context,
                await _trans('unauthorized', lang, "❌ غير مصرح"),
                parse_mode=None,
            )
            return
        args = context.args or []
        if len(args) < 2:
            await _safe_edit_or_send(
                update, context,
                "📝 /grant <user_id> <days>",
                parse_mode=None,
            )
            return
        try:
            target_id = int(args[0])
            days = int(args[1])
            if target_id <= 0 or days < 1 or days > 365:
                raise ValueError
        except (ValueError, TypeError):
            await _safe_edit_or_send(update, context,
                                     "❌ قيم غير صالحة", parse_mode=None)
            return
        user_row = await DB.fetchone(
            "SELECT user_id FROM users WHERE user_id=?", (target_id,))
        if not user_row:
            await _safe_edit_or_send(
                update, context,
                "❌ المستخدم غير موجود",
                parse_mode=None,
            )
            return
        plan_row = await DB.fetchone("SELECT id FROM plans WHERE is_gift=1 LIMIT 1")
        if not plan_row:
            plan_row = await DB.fetchone(
                "SELECT id FROM plans WHERE is_active=1 AND is_gift=0 LIMIT 1"
            )
        plan_row_d = _row_to_dict(plan_row)
        plan_id = plan_row_d.get('id') if plan_row_d else None
        if plan_id is None:
            await _safe_edit_or_send(update, context,
                                     "❌ لا توجد خطط", parse_mode=None)
            return
        success = await DB.grant_subscription_days(
            target_id, days, plan_id=plan_id, provider='manual'
        )
        if success:
            try:
                await DB.invalidate_subscription_cache(target_id)
            except Exception:
                pass
            msg = await _trans('grant_success_with_id', lang,
                               "✅ تم منح {days} يوم للمستخدم <code>{user_id}</code>")
            try:
                msg = msg.format(days=days, user_id=_mask_id(target_id))
            except (KeyError, IndexError):
                pass
            await _safe_edit_or_send(update, context, msg, parse_mode='HTML')
            await user_cache.invalidate(target_id)
        else:
            await _safe_edit_or_send(
                update, context,
                await _trans('grant_failed', lang, "❌ فشل المنح"),
                parse_mode=None,
            )

    @staticmethod
    async def gift_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        plans = await DB.get_gift_plans()
        if not plans:
            await _safe_edit_or_send(
                update, context,
                await _trans('no_gift_plans', lang, "📭 لا توجد خطط هدايا"),
                parse_mode=None,
            )
            return
        kb = []
        for plan in plans:
            p_d = _row_to_dict(plan)
            p_id = p_d.get('id')
            p_days = p_d.get('days', '?')
            p_price = p_d.get('price', '?')
            if p_id is None:
                continue
            kb.append([InlineKeyboardButton(
                f"🎁 {p_days} يوم - {p_price} ⭐",
                callback_data=f"buy_gift:{p_id}"
            )])
        back_text = KeyboardFactory.get_text("back", lang)
        kb.append([InlineKeyboardButton(back_text, callback_data=CB.BACK)])
        await _safe_edit_or_send(
            update, context,
            await _trans('gift_plans_text', lang, "💎 اختر خطة هدية:"),
            reply_markup=InlineKeyboardMarkup(kb), parse_mode=None,
        )

    @staticmethod
    async def redeem_gift(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        args = context.args or []
        if not args:
            await _safe_edit_or_send(
                update, context,
                await _trans('send_code', lang,
                             "📝 أرسل الكود: /redeem_gift <الكود>"),
                parse_mode=None,
            )
            return
        code = args[0].strip()
        if len(code) < 4 or len(code) > 50:
            await _safe_edit_or_send(
                update, context,
                await _trans('invalid_code', lang, "❌ كود غير صالح"),
                parse_mode=None,
            )
            return
        result = await DB.redeem_gift_code(user_id, code)
        if isinstance(result, tuple):
            success, days = result
        else:
            success, days = (bool(result), 0)
        if success and days > 0:
            try:
                await DB.invalidate_subscription_cache(user_id)
            except Exception:
                pass
            msg = await _trans('gift_redeemed', lang,
                               "🎉 تم تفعيل اشتراك {days} يوم")
            try:
                msg = msg.format(days=days)
            except (KeyError, IndexError):
                pass
            await _safe_edit_or_send(update, context, msg, parse_mode=None)
            await user_cache.invalidate(user_id)
        elif days == -1:
            await _safe_edit_or_send(
                update, context,
                await _trans('own_code', lang, "❌ لا يمكنك استخدام كودك الخاص"),
                parse_mode=None,
            )
        else:
            await _safe_edit_or_send(
                update, context,
                await _trans('invalid_code', lang, "❌ كود غير صالح"),
                parse_mode=None,
            )

    # ═══════════════════════════════════════════════════════════════
    # ✅ v7.5.25: أوامر تشخيص قاعدة البيانات
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def db_diag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if not CONFIG.is_developer(user_id):
            return

        await _safe_edit_or_send(
            update, context,
            "⏳ <b>جاري التشخيص...</b>\n\n"
            "<i>قد يستغرق 5-10 ثواني</i>",
            parse_mode='HTML',
        )

        try:
            from db_diagnostics import diagnose_db
            result = await diagnose_db()

            if len(result) > 4000:
                parts = [result[i:i+4000] for i in range(0, len(result), 4000)]
                for i, part in enumerate(parts, 1):
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"<i>({i}/{len(parts)})</i>\n{part}",
                        parse_mode='HTML'
                    )
                    await asyncio.sleep(0.3)
            else:
                await context.bot.send_message(
                    chat_id=user_id, text=result,
                    parse_mode='HTML'
                )
        except ImportError:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ ملف <code>db_diagnostics.py</code> غير موجود في المشروع",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"db_diag: {e}", exc_info=True)
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ فشل التشخيص: <code>{escape(str(e)[:200])}</code>",
                parse_mode='HTML'
            )

    @staticmethod
    async def db_vacuum(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if not CONFIG.is_developer(user_id):
            return

        await _safe_edit_or_send(
            update, context,
            "⏳ <b>جاري تنظيف قاعدة البيانات...</b>\n\n"
            "<i>قد يستغرق 30-60 ثانية. البوت سيبقى مستجيباً.</i>",
            parse_mode='HTML',
        )

        try:
            from db_diagnostics import vacuum_analyze_tables
            result = await vacuum_analyze_tables()
            await context.bot.send_message(
                chat_id=user_id, text=result,
                parse_mode='HTML'
            )
        except ImportError:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ ملف <code>db_diagnostics.py</code> غير موجود",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"db_vacuum: {e}", exc_info=True)
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ فشل التنظيف: <code>{escape(str(e)[:200])}</code>",
                parse_mode='HTML'
            )


__all__ = ['CommandHandlers']