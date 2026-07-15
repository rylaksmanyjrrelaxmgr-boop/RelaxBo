import re
import json
import time
import random
import hashlib
import secrets
import logging
import traceback
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, ChatPermissions, LabeledPrice
from telegram.ext import ContextTypes

from config import *
from database import *
from utils import *

logger = logging.getLogger(__name__)

class CallbackData:
    MAIN_MENU = "main_menu"
    CHANNELS_MY = "channels:my_channels"
    CHANNELS_ADD = "channels:add"
    CHANNELS_DELETE_PREFIX = "channels:delete:"
    CHANNELS_SELECT_PREFIX = "channels:select:"
    POSTS_ADD_15 = "posts:add_15"
    POSTS_PUBLISH_ONE = "posts:publish_one"
    POSTS_MY = "posts:my_posts"
    POSTS_RECYCLE = "posts:recycle"
    POSTS_DELETE_SINGLE_PREFIX = "posts:delete_single:"
    POSTS_CONFIRM_CLEAR_ALL_PREFIX = "posts:confirm_clear_all:"
    POSTS_CLEAR_ALL_PREFIX = "posts:clear_all:"
    STATS_PENDING = "stats:pending"
    STATS_FULL = "stats:full"
    GROUPS_MY = "groups:my_groups"
    GROUPS_SETTINGS_PREFIX = "groups:settings:"
    SETTINGS_MENU = "settings:menu"
    SETTINGS_TOGGLE_AUTO_PUBLISH = "settings:toggle_auto_publish"
    SETTINGS_TOGGLE_AUTO_RECYCLE = "settings:toggle_auto_recycle"
    SCHEDULE_MENU_PREFIX = "schedule:menu:"
    SCHEDULE_SET_INTERVAL_MINUTES_PREFIX = "schedule:set_interval_minutes:"
    SCHEDULE_SET_INTERVAL_HOURS_PREFIX = "schedule:set_interval_hours:"
    SCHEDULE_SET_INTERVAL_DAYS_PREFIX = "schedule:set_interval_days:"
    SCHEDULE_SET_DAYS_PREFIX = "schedule:set_days:"
    SCHEDULE_SET_DATES_PREFIX = "schedule:set_dates:"
    SCHEDULE_SET_PUBLISH_TIME_PREFIX = "schedule:set_publish_time:"
    SCHEDULE_DAY_SELECT_PREFIX = "schedule:day_select:"
    SCHEDULE_SAVE_DAYS = "schedule:save_days"
    SECURITY_LINKS_PREFIX = "security:links:"
    SECURITY_MENTIONS_PREFIX = "security:mentions:"
    SECURITY_SLOWMODE_PREFIX = "security:slowmode:"
    SECURITY_BANNED_WORDS_MENU_PREFIX = "security:banned_words_menu:"
    SECURITY_WELCOME_PREFIX = "security:welcome:"
    SECURITY_GOODBYE_PREFIX = "security:goodbye:"
    SECURITY_CLOSE = "security:close"
    BANNED_WORDS_ADD_PREFIX = "banned_words:add:"
    BANNED_WORDS_LIST_PREFIX = "banned_words:list:"
    BANNED_WORDS_REMOVE_PREFIX = "banned_words:remove:"
    HELP = "help"
    SUPPORT_MENU = "support:menu"
    SUPPORT_HELP = "support:help"
    SUPPORT_TICKET = "support:ticket"
    TRIAL = "trial"
    SUBSCRIBE_MENU = "subscribe:menu"
    BUY_SUBSCRIPTION_1 = "buy:subscription_1"
    BUY_SUBSCRIPTION_2 = "buy:subscription_2"
    BUY_SUBSCRIPTION_30 = "buy:subscription_30"
    BUY_SUBSCRIPTION_90 = "buy:subscription_90"
    DEVELOPER = "developer"
    UPDATES = "updates"
    REFERRAL_MENU = "referral:menu"
    REFERRAL_COPY_LINK_PREFIX = "referral:copy_link:"
    REFERRAL_CLAIM_REWARD = "referral:claim_reward"
    REFERRAL_LIST = "referral:list"
    REMINDER_MENU = "reminder:menu"
    REMINDER_TOGGLE_SUB = "reminder:toggle_sub"
    REMINDER_TOGGLE_DAILY = "reminder:toggle_daily"
    REMINDER_TOGGLE_WEEKLY = "reminder:toggle_weekly"
    REMINDER_SET_DAYS = "reminder:set_days"
    REMINDER_SET_LANG = "reminder:set_lang"
    REMINDER_LANG_PREFIX = "reminder:lang:"
    TRANSLATION_MENU = "translation:menu"
    TRANSLATION_OFF = "translation:off"
    TRANSLATION_SET_PREFIX = "translation:set:"
    ADMIN_PANEL = "admin:panel"
    ADMIN_USERS = "admin:users"
    ADMIN_BANNED_USERS = "admin:banned_users"
    ADMIN_UNBAN_ALL_USERS = "admin:unban_all_users"
    ADMIN_ALL_CHANNELS = "admin:all_channels"
    ADMIN_BANNED_CHANNELS = "admin:banned_channels"
    ADMIN_ACTIVATE_ALL_CHANNELS = "admin:activate_all_channels"
    ADMIN_GROUPS = "admin:groups"
    ADMIN_BANNED_GROUPS = "admin:banned_groups"
    ADMIN_UNBAN_ALL_GROUPS = "admin:unban_all_groups"
    ADMIN_BOT_CHANNELS = "admin:bot_channels"
    ADMIN_BANNED_BOT_CHANNELS = "admin:banned_bot_channels"
    ADMIN_UNBAN_ALL_BOT_CHANNELS = "admin:unban_all_bot_channels"
    ADMIN_MONITOR_USERS = "admin:monitor_users"
    ADMIN_ADD_ADMIN = "admin:add_admin"
    ADMIN_REMOVE_ADMIN = "admin:remove_admin"
    ADMIN_RAM = "admin:ram"
    ADMIN_STATS = "admin:stats"
    ADMIN_METRICS = "admin:metrics"
    ADMIN_BACKUP = "admin:backup"
    ADMIN_RESTORE_BACKUP = "admin:restore_backup"
    ADMIN_RESTORE_BACKUP_SELECT_PREFIX = "admin:restore_backup_select:"
    ADMIN_BACKUP_SETTINGS = "admin:backup_settings"
    ADMIN_TOGGLE_AUTO_BACKUP = "admin:toggle_auto_backup"
    ADMIN_CHANGE_INTERVAL = "admin:change_interval"
    ADMIN_SEND_UPDATE = "admin:send_update"
    ADMIN_SET_UPDATE_CHANNEL = "admin:set_update_channel"
    ADMIN_SHOW_UPDATE_CHANNEL = "admin:show_update_channel"
    ADMIN_UPDATES = "admin:updates"
    ADMIN_FORCE_SUBSCRIBE = "admin:force_subscribe"
    ADMIN_SET_FORCE_CHANNEL = "admin:set_force_channel"
    ADMIN_BROADCAST = "admin:broadcast"
    ADMIN_CONFIRM_BROADCAST = "admin:confirm_broadcast"
    ADMIN_SUPPORT_TICKETS = "admin:support_tickets"
    ADMIN_DELETE_ALL_TICKETS = "admin:delete_all_tickets"
    ADMIN_CONFIRM_DELETE_TICKETS = "admin:confirm_delete_tickets"
    ADMIN_MANAGE_SENDCODE = "admin:manage_sendcode"
    ADMIN_SET_SENDCODE_USER = "admin:set_sendcode_user"
    ADMIN_SHOW_LOG_CHANNEL = "admin:show_log_channel"
    ADMIN_SET_LOG_CHANNEL = "admin:set_log_channel"
    ADMIN_REPLIES = "admin:replies"
    ADMIN_ADD_REPLY = "admin:add_reply"
    ADMIN_LIST_REPLIES = "admin:list_replies"
    ADMIN_DEL_REPLY = "admin:del_reply"
    ADMIN_BANNED_WORDS = "admin:banned_words"
    ADMIN_ADD_BANNED_WORD = "admin:add_banned_word"
    ADMIN_LIST_BANNED_WORDS = "admin:list_banned_words"
    ADMIN_REMOVE_BANNED_WORD = "admin:remove_banned_word"
    ADMIN_CREATE_CONTEST = "admin:create_contest"
    ADMIN_DECLARE_WINNER = "admin:declare_winner"
    PANEL_LOCK_PREFIX = "panel:lock:"
    PANEL_UNLOCK_PREFIX = "panel:unlock:"
    PANEL_CLOSE = "panel:close"
    CHECK_SUBSCRIBE = "check_subscribe"
    BACK = "back"
    CANCEL_SESSION = "cancel_session"
    ADVANCED_ACTIONS = "advanced_actions"
    GROUP_ACTION_BAN = "group_action:ban"
    GROUP_ACTION_MUTE = "group_action:mute"
    GROUP_ACTION_WARN = "group_action:warn"
    GROUP_ACTION_KICK = "group_action:kick"
    GROUP_ACTION_RESTRICT = "group_action:restrict"
    GROUP_ACTION_PIN = "group_action:pin"
    GROUP_ACTION_LOG = "group_action:log"
    GROUP_ACTION_UNBAN = "group_action:unban"
    GROUP_MUTE_DURATION_5 = "group_mute_duration:5"
    GROUP_MUTE_DURATION_30 = "group_mute_duration:30"
    GROUP_MUTE_DURATION_60 = "group_mute_duration:60"
    GROUP_MUTE_DURATION_720 = "group_mute_duration:720"
    GROUP_MUTE_DURATION_1440 = "group_mute_duration:1440"
    GROUP_MUTE_DURATION_10080 = "group_mute_duration:10080"
    GROUP_MUTE_DURATION_PERMANENT = "group_mute_duration:permanent"
    SECURITY_SELECT_GROUP = "security_select_group:"
    SECURITY_REFRESH_GROUPS = "security_refresh_groups"
    PENALTY_MENU = "penalty_menu"
    PENALTY_KICK = "penalty:kick"
    PENALTY_BAN = "penalty:ban"
    PENALTY_MUTE = "penalty:mute"
    PUBLISH_ALL_CHANNELS = "publish_all_channels"
    CHANNEL_STATS = "channel_stats"
    CHANNEL_GROWTH = "channel_growth"
    CHANNEL_STATS_REFRESH = "channel_stats_refresh"
    MY_CHANNEL_STATS = "my_channel_stats"
    ADMIN_TOGGLE_CHANNEL_BAN_PREFIX = "admin:toggle_channel_ban:"
    ADMIN_TOGGLE_GROUP_BAN_PREFIX = "admin:toggle_group_ban:"
    CONTESTS_MENU = "contests_menu"
    CONTEST_JOIN_PREFIX = "contest_join:"
    CONTEST_WINNERS = "contest_winners"
    CONTESTS_BACK = "contests_back"
    ADMIN_AUTO_REPLY = "admin_auto_reply"
    ADMIN_AUTO_REPLY_SELECT_PREFIX = "admin_auto_reply_select:"
    AUTO_REPLY_TOGGLE_PREFIX = "auto_reply_toggle:"
    AUTO_REPLY_ADMINS_PREFIX = "auto_reply_admins:"
    AUTO_REPLY_RESET_PREFIX = "auto_reply_reset:"
    AUTO_REPLY_CONFIRM_RESET_PREFIX = "auto_reply_confirm_reset:"
    AUTO_REPLY_CANCEL_PREFIX = "auto_reply_cancel:"
    AUTO_REPLY_STATS_PREFIX = "auto_reply_stats:"
    USER_AUTO_REPLY_TOGGLE_PREFIX = "user_auto_reply_toggle:"
    NSFW_SETTINGS = "nsfw_settings"
    NSFW_TOGGLE = "nsfw_toggle"
    NSFW_THRESHOLD_SET = "nsfw_threshold_set"
    UPDATE_ADMINS = "update_admins"

WELCOME_REPLIES = {}
FAQ_REPLIES = {}
POSITIVE_REPLIES = {}
RELIGIOUS_REPLIES = {}
JOKE_REPLIES = {}
MOTIVATIONAL_REPLIES = {}
SOCIAL_REPLIES = {}
ADMIN_REPLIES = {}
REQUEST_REPLIES = {}
ABOUT_BOT_REPLIES = {}
EXTRA_REPLIES = {}
ALL_REPLIES = {}

def load_replies():
    global WELCOME_REPLIES, FAQ_REPLIES, POSITIVE_REPLIES, RELIGIOUS_REPLIES, JOKE_REPLIES, MOTIVATIONAL_REPLIES, SOCIAL_REPLIES, ADMIN_REPLIES, REQUEST_REPLIES, ABOUT_BOT_REPLIES, EXTRA_REPLIES, ALL_REPLIES
    WELCOME_REPLIES = {
        "مرحباً": "أهلاً وسهلاً بك في مجموعتنا 🤍",
        "السلام عليكم": "وعليكم السلام ورحمة الله وبركاته 🌹",
        "اهلاً": "أهلاً بك، تشرفنا 🙏",
        "هلا": "هلا والله، نورت المجموعة ✨",
        "مرحبا بكم": "أهلاً بكم جميعاً، تشرفنا بتواجدكم 🌸",
        "هلا والله": "هلا بك، نورت الدنيا 🌹",
        "مرحبا مليون": "مليون مرحبة، نورت ✨",
        "اهلا وسهلا": "أهلاً وسهلاً، حياك الله 🙏",
        "نورت": "نورت المجموعة بوجودك 🌸",
        "شرفت": "شرفتنا يا غالي 🌹",
        "تشرفنا": "تشرفنا بمعرفتك 🙏",
        "منور": "منور الدنيا يا حلو 🌸",
        "ياهلا": "ياهلا بك مليون 🌹",
        "اهلين": "أهلين وسهلين ✨",
        "مسا الخير": "مسا النور 🌙",
        "صباح الخير": "صباح النور 🌞",
        "تصبح على خير": "وأنت من أهله 🌙",
        "مساء النور": "أهلين وسهلين 🌸",
        "نورت الدنيا": "أنت النور 🌹",
        "فرحتنا": "فرحتنا بوجودك 🤍"
    }
    FAQ_REPLIES = {
        "كيف حالك": "الحمد لله، بخير وأنت؟ ❤️",
        "شو اخبارك": "كل الخير، كيفك أنت؟ 🌹",
        "اخبارك": "بخير، الحمد لله 🙏",
        "شنو اخبارك": "الحمد لله، كيفك أنت؟ ❤️",
        "شخبارك": "شخبارك أنت؟ 🌸",
        "وينكم": "هني موجودين، شنو المطلوب؟ 👋",
        "وينك": "أنا هنا، شنو تحتاج؟ 🤖",
        "شنو اسمك": "أنا البوت، تحت أمرك 🙏",
        "وش اسمك": "أنا البوت، تشرفنا 🤖",
        "منو انت": "أنا البوت، مساعد المجموعة 🛡️",
        "ايش اسمك": "اسمي البوت، سعيد بمعرفتك 🌹",
        "كيفك انت": "بخير الحمد لله 🌸",
        "وشلونك": "الحمد لله، كيفك أنت؟ ❤️",
        "كيف الأحوال": "كل تمام، الحمد لله 🙏",
        "شو وضعك": "تمام، الحمد لله 🌹",
        "كيف الحال": "الحال دوماً بخير 🌸",
        "ايش اخبارك": "الخبر كله خير ❤️",
        "اخبار الدنيا": "الدنيا بخير 🌹",
        "شو جديد": "الجديد هو وجودك معنا ✨",
        "ايش جديدك": "جديدك يفرحنا 🌸",
        "كيف اليوم": "اليوم جميل بحضورك 🌹",
        "شو تسوي": "أساعد الناس، وهني بانتظارك 🤖",
        "اين انت": "أنا هنا، تحت أمرك 🙏",
        "شنو تسوي": "أخدم المجموعة وأديرها 📡",
        "ماذا تفعل": "أساعد في إدارة المجموعة 🛡️"
    }
    POSITIVE_REPLIES = {
        "شكراً": "العفو، تحت أمرك دائماً ❤️",
        "شكرا": "العفو، أهلين 🙏",
        "تسلم": "تسلم يا غالي 🌸",
        "تسلمي": "تسلمي يا غالية 🌹",
        "يسلمو": "يسلم قلبك ❤️",
        "يعطيك العافية": "يعافيك ربي ❤️",
        "يعطيك الف عافية": "الله يعافيك 🌹",
        "ربي يوفقك": "وإياك يا رب 🌸",
        "جزاك الله خير": "وإياكم، الله يبارك فيك 🌹",
        "الف شكر": "ألف شكر لك 🙏",
        "مشكور": "مشكور يا غالي 🌸",
        "مشكورة": "مشكورة يا غالية 🌹",
        "شكراً جزيلاً": "الشكر لله ثم لك ❤️",
        "يعطيك الصحة": "الله يعافيك 🙏",
        "ربي يعطيك العافية": "يعافيك ربي 🌹",
        "ممتاز": "شكراً لك 🌟",
        "رائع": "يعجبني هذا 🌸",
        "جميل": "روعة 🌹",
        "الله يبارك فيك": "وفيك بارك الله 🙏",
        "تقبل مروري": "نورتنا بمرورك 🌸"
    }
    RELIGIOUS_REPLIES = {
        "ما شاء الله": "تبارك الرحمن 🤍",
        "ماشاءالله": "تبارك الله 🌹",
        "ما شاء الله تبارك الله": "الله يبارك فيك 🙏",
        "الحمد لله": "الحمد لله دائماً وأبداً 🙏",
        "سبحان الله": "سبحان الله وبحمده 🌹",
        "سبحان الله وبحمده": "سبحان الله العظيم 🌸",
        "اللهم صل على محمد": "اللهم صل وسلم وبارك على نبينا محمد 🌸",
        "صل على النبي": "اللهم صل على محمد 🌹",
        "استغفر الله": "ربي اغفر لي ولوالديّ 🙏",
        "استغفر الله العظيم": "الله أكبر، أستغفرك وأتوب إليك 🤍",
        "لا اله الا الله": "لا إله إلا الله محمد رسول الله 🙏",
        "الله اكبر": "الله أكبر كبيراً 🌹",
        "الحمدلله": "الحمد لله رب العالمين 🙏",
        "ربي": "لبيك يا رب 🌸",
        "اللهم": "آمين يا رب العالمين 🤍",
        "سبحانه": "سبحانه وتعالى 🙏",
        "تعالى الله": "الله أعلى وأعلم 🌹",
        "بسم الله": "بسم الله الرحمن الرحيم 🤍",
        "توكلت على الله": "حسبي الله ونعم الوكيل 🙏",
        "رب العالمين": "رب السماوات والأرض 🌹",
        "الرحمن": "بسم الله الرحمن الرحيم 🤍",
        "الرحيم": "الرحيم بعباده 🙏",
        "الملك": "الملك القدوس 🌹",
        "القدوس": "سبحان القدوس 🤍",
        "السلام": "السلام عليكم ورحمة الله 🌸"
    }
    JOKE_REPLIES = {
        "ضحك": "😂😂",
        "نكتة": "مرة واحد قال للبوت: وينك؟ قال البوت: هني 👻",
        "مزح": "😅😅",
        "فكة": "😂🤣",
        "وناسة": "🤩🤩",
        "طقطقة": "😂😂",
        "خبلت": "هههههه 🤣",
        "هههه": "😂🤣",
        "ضحكتني": "أنا مبسوط إنك ضحكت 😊",
        "ههههههه": "ههههههههه 🤣😂",
        "ضحكك": "يضحكني حضورك 😂",
        "نكتة جديدة": "مرة وحدة سألت البوت: أيش تسوي؟ قال: أنشر وأحمي 🤖",
        "طشة": "😂😂",
        "مموت": "ههههه، ضحكتني 🤣",
        "قهقهة": "ههههههههه 😂",
        "ضحك عالي": "ههههههههههه 🤣",
        "نكتة حلوة": "أحلى نكتة هي وجودك معنا 😊",
        "وناسة": "جو وناسة 🤩",
        "اخبارك": "تضحك وتبسط 😂",
        "طقطقة حلوة": "هههه، طق طق 🤣",
        "فكه": "فكة عسل 😂",
        "خوش واحد": "ههههه 🤣",
        "موتني": "موتني ضحك 😂",
        "نكتة اليوم": "اليوم يومك 😊",
        "حلوة": "حلوتك 🤩",
        "ايش هالضحك": "ضحكك يفرحني 😂",
        "يهبل": "ههههه 🤣",
        "يكسر": "ههههههه 🤣😂",
        "مزة": "ههههه 🤣",
        "جو": "جو حلو 😊"
    }
    MOTIVATIONAL_REPLIES = {
        "تعبت": "إرتاح شوي، تستاهل الراحة 😊",
        "زعلان": "لا تزعل، كل شيء بيصير خير ❤️",
        "فرحان": "الله يفرح قلبك 😊",
        "ناجح": "ألف مبروك، تستاهل كل خير 🎉",
        "فائز": "مبروك الفوز، أنت تستاهل 🏆",
        "متعب": "خذ قسط من الراحة 🌸",
        "محبط": "لا تحبط، النجاح قريب 💪",
        "متفائل": "تفاؤلك خير 🌹",
        "حزين": "كل شيء سيكون بخير ❤️",
        "مبسوط": "أجمل شعور هو السعادة 😊",
        "متحمس": "حماسك جميل 🔥",
        "مبدع": "إبداعك رائع 🌟",
        "متطور": "أنت تتطور باستمرار 🚀",
        "طموح": "طموحك يوصلك للنجاح 💫",
        "ناجح": "أنت ناجح دائماً 🎉"
    }
    SOCIAL_REPLIES = {
        "كيفك": "بخير الحمد لله، وأنت؟ 🌹",
        "كيفك انت": "بخير، تسلم ❤️",
        "اخبار العائلة": "كلهم بخير، الحمد لله 🙏",
        "والديك": "بخير، الحمد لله 🌸",
        "الاهل": "الحمد لله، كلهم بخير 🌹",
        "الصحة": "الحمد لله على كل حال 🙏",
        "العمل": "الحمد لله، أموره طيبة 🌸",
        "الدراسة": "بالتوفيق إن شاء الله 📚",
        "الجامعة": "الله يوفقك يارب 🌹",
        "المدرسة": "بالتوفيق والنجاح 🌸",
        "البيت": "الحمد لله، بيتنا بخير 🙏",
        "السفر": "الله يسهل لك 🌹",
        "السيارة": "سلامتك يا رب 🚗",
        "السكن": "الحمد لله، مستقرين 🌸",
        "المال": "الحمد لله، رزق حلال 🙏",
        "الزواج": "الله يبارك لك 🌹",
        "العزوبية": "الله يرزقك الزوجة الصالحة 🙏",
        "الأولاد": "الله يبارك لك فيهم 🌸",
        "البنات": "الله يحفظهم لك 🌹",
        "العائلة": "الله يجمع شملكم 🤍"
    }
    ADMIN_REPLIES = {
        "ممنوع": "تم التنبيه، يرجى احترام قوانين المجموعة 🚫",
        "انتبه": "رجاءً انتبه للقوانين ⚠️",
        "قوانين": "قوانين المجموعة موجودة في الوصف 📋",
        "مخالفة": "تنبيه: هذا مخالف للقوانين 🚫",
        "تحذير": "تحذير أول، يرجى الالتزام بالقوانين ⚠️",
        "طرد": "سيتم تطبيق العقوبات 🚫",
        "حظر": "تم حظر المخالف 🚫",
        "كتم": "تم كتم المخالف 🔇",
        "سجل": "تم تسجيل المخالفة 📝",
        "تنبيه": "تنبيه هام يرجى قراءة القوانين 📋"
    }
    REQUEST_REPLIES = {
        "بليز": "حاضر، بس أرسل طلبك بالتفصيل 📝",
        "من فضلك": "تفضل، أنا هنا للمساعدة 🤖",
        "تكرم": "أمرك يا غالي 🌹",
        "لو سمحت": "تفضل، أنا جاهز 🙏",
        "عندي طلب": "أرسل طلبك وسأساعدك 💡",
        "طلب": "تفضل بطلبك 📝",
        "سؤال": "اسأل، وأنا هنا للإجابة ❓",
        "استفسار": "تفضل بالاستفسار 📋",
        "مساعدة": "كيف أقدر أساعدك؟ 🤖",
        "دعم": "أنا هنا لدعمك 💪",
        "شكوى": "اشرح شكوتك وسنحلها 📞",
        "مشكلة": "اشرح مشكلتك، سأحاول مساعدتك 💡",
        "اقتراح": "تفضل باقتراحك، نرحب بكل فكرة 💡",
        "فكرة": "شاركنا فكرتك الجميلة 🌟",
        "رأي": "نرحب برأيك القيم 📝"
    }
    ABOUT_BOT_REPLIES = {
        "مين انت": "أنا البوت، مساعد لإدارة المجموعات 🤖",
        "ايش تسوي": "أساعد في إدارة المجموعات، النشر، الأمان، والكثير 📋",
        "مهمتك": "تنظيم المجموعات وحمايتها من المزعجين 🛡️",
        "شغلك": "أنشر المنشورات، أحافظ على الأمان، وأدير القنوات 📡",
        "ايش تقدر": "أقدر أساعدك في إدارة القناة والمجموعة 💪",
        "مهاراتك": "النشر التلقائي، الأمان، الردود، والإحصائيات 📊",
        "شو اختصاصك": "إدارة القنوات والمجموعات بكل احترافية 🎯",
        "ليش انت هنا": "لأخدمكم وأساعد في تنظيم المجموعة 🌸",
        "عرف نفسك": "أنا بوت مساعد، تحت أمركم 🙏",
        "شنو فائدتك": "أسهل عليك إدارة القناة والمجموعة 🚀"
    }
    EXTRA_REPLIES = {
        "تمام": "تمام يا غالي 🌸",
        "اوك": "أوكي، تحت أمرك 🙏",
        "حاضر": "حاضر، أنا جاهز 💪",
        "ان شاء الله": "إن شاء الله خير 🌹",
        "باذن الله": "بإذن الله 🙏",
        "مع السلامة": "مع السلامة، تشرفنا بك 🌸",
        "باي": "باي، نورت 🌹",
        "سلام": "سلام، الله يحفظك 🙏",
        "ياعيني": "ياعيني عليك 🌹",
        "ياحلو": "حلوك الله 🌸"
    }
    ALL_REPLIES = {}
    ALL_REPLIES.update(WELCOME_REPLIES)
    ALL_REPLIES.update(FAQ_REPLIES)
    ALL_REPLIES.update(POSITIVE_REPLIES)
    ALL_REPLIES.update(RELIGIOUS_REPLIES)
    ALL_REPLIES.update(JOKE_REPLIES)
    ALL_REPLIES.update(MOTIVATIONAL_REPLIES)
    ALL_REPLIES.update(SOCIAL_REPLIES)
    ALL_REPLIES.update(ADMIN_REPLIES)
    ALL_REPLIES.update(REQUEST_REPLIES)
    ALL_REPLIES.update(ABOUT_BOT_REPLIES)
    ALL_REPLIES.update(EXTRA_REPLIES)

load_replies()

_user_language_lock = asyncio.Lock()
_user_translation_cache_lock = asyncio.Lock()

def get_text(user_id: int, key: str) -> str:
    lang = user_language.get(user_id, "ar")
    translations = TRANSLATIONS.get(lang, TRANSLATIONS.get("ar", {}))
    return translations.get(key, key)

async def set_user_language(user_id: int, lang: str):
    async with _user_language_lock:
        user_language[user_id] = lang

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    channels = await db_get_channels(uid)
    active = None
    if channels:
        try:
            active = await db_get_active_channel(uid)
            if active is not None:
                channel_exists = False
                for ch in channels:
                    if ch[0] == active:
                        channel_exists = True
                        break
                if not channel_exists:
                    active = channels[0][0]
                    await db_set_active_channel(uid, active)
            else:
                active = channels[0][0]
                await db_set_active_channel(uid, active)
        except:
            active = channels[0][0] if channels else None
    cnt = 0
    ch_display = get_text(uid, "no_channels")
    if active is not None:
        try:
            cnt = await db_unpublished_count(active)
            ch_info = await db_get_channel_info(active)
            if ch_info and len(ch_info) >= 2:
                ch_tele_id = ch_info[0] if ch_info[0] is not None else "unknown"
                ch_name = ch_info[1] if ch_info[1] is not None else ch_tele_id
                ch_display = f"{ch_name} ({ch_tele_id})"
        except:
            ch_display = get_text(uid, "no_channels")
    my_groups = 0
    try:
        my_groups = await db_get_user_groups_count(uid)
    except:
        my_groups = 0
    has_sub = False
    try:
        has_sub = await db_has_active_subscription(uid)
    except:
        has_sub = False
    sub_text = get_text(uid, "subscribed") if has_sub else get_text(uid, "not_subscribed")
    auto_status = False
    try:
        auto_status = await db_auto_status(uid)
    except:
        auto_status = False
    auto_text = get_text(uid, "auto_on") if auto_status else get_text(uid, "auto_off")
    title = get_text(uid, "main_title").format(BOT_NAME, uid, my_groups, sub_text, ch_display, cnt, auto_status)
    updates_channel = None
    try:
        updates_channel = await db_get_updates_channel()
    except:
        updates_channel = None
    keyboard = []
    keyboard.append([InlineKeyboardButton(get_text(uid, "my_groups_btn"), callback_data=CallbackData.GROUPS_MY), InlineKeyboardButton(get_text(uid, "add_channel"), callback_data=CallbackData.CHANNELS_ADD)])
    keyboard.append([InlineKeyboardButton(get_text(uid, "my_channels"), callback_data=CallbackData.CHANNELS_MY), InlineKeyboardButton(get_text(uid, "settings_btn"), callback_data=CallbackData.SETTINGS_MENU)])
    if channels:
        keyboard.append([InlineKeyboardButton(get_text(uid, "add_15_posts"), callback_data=CallbackData.POSTS_ADD_15), InlineKeyboardButton(get_text(uid, "publish_one"), callback_data=CallbackData.POSTS_PUBLISH_ONE)])
        keyboard.append([InlineKeyboardButton(get_text(uid, "my_posts_btn"), callback_data=CallbackData.POSTS_MY), InlineKeyboardButton(get_text(uid, "recycle"), callback_data=CallbackData.POSTS_RECYCLE)])
        keyboard.append([InlineKeyboardButton(f"{get_text(uid, 'stats_btn')} ({cnt})", callback_data=CallbackData.STATS_PENDING), InlineKeyboardButton(get_text(uid, "my_stats_btn"), callback_data=CallbackData.STATS_FULL)])
        if active is not None:
            keyboard.append([InlineKeyboardButton(get_text(uid, "schedule_btn"), callback_data=f"{CallbackData.SCHEDULE_MENU_PREFIX}{active}"), InlineKeyboardButton(get_text(uid, "channel_stats"), callback_data=f"{CallbackData.CHANNEL_STATS}:{active}")])
        keyboard.append([InlineKeyboardButton(get_text(uid, "my_channels_summary"), callback_data=CallbackData.MY_CHANNEL_STATS), InlineKeyboardButton(get_text(uid, "my_rank_btn"), callback_data="rank")])
        keyboard.append([InlineKeyboardButton(get_text(uid, "top_10_btn"), callback_data="top"), InlineKeyboardButton(get_text(uid, "schedule_post_btn"), callback_data="schedule_post")])
        keyboard.append([InlineKeyboardButton(get_text(uid, "publish_all"), callback_data=CallbackData.PUBLISH_ALL_CHANNELS)])
    keyboard.append([InlineKeyboardButton(get_text(uid, "help_btn"), callback_data=CallbackData.HELP), InlineKeyboardButton(get_text(uid, "trial_btn"), callback_data=CallbackData.TRIAL)])
    keyboard.append([InlineKeyboardButton(get_text(uid, "subscribe_btn"), callback_data=CallbackData.SUBSCRIBE_MENU), InlineKeyboardButton(get_text(uid, "developer_btn"), callback_data=CallbackData.DEVELOPER)])
    keyboard.append([InlineKeyboardButton(get_text(uid, "language_btn"), callback_data="language"), InlineKeyboardButton(get_text(uid, "support_btn"), callback_data=CallbackData.SUPPORT_MENU)])
    keyboard.append([InlineKeyboardButton(get_text(uid, "referral"), callback_data=CallbackData.REFERRAL_MENU), InlineKeyboardButton(get_text(uid, "reminder_settings"), callback_data=CallbackData.REMINDER_MENU)])
    keyboard.append([InlineKeyboardButton(get_text(uid, "translation_settings"), callback_data=CallbackData.TRANSLATION_MENU)])
    keyboard.append([InlineKeyboardButton(get_text(uid, "contests_menu"), callback_data=CallbackData.CONTESTS_MENU)])
    if updates_channel:
        keyboard.append([InlineKeyboardButton(get_text(uid, "updates_btn"), callback_data=CallbackData.UPDATES)])
    keyboard.append([InlineKeyboardButton(get_text(uid, "add_to_group"), url=f"https://t.me/{BOT_USERNAME}?startgroup")])
    is_admin = False
    try:
        is_admin = (uid == PRIMARY_OWNER_ID) or (await is_bot_admin(uid))
    except:
        is_admin = False
    if is_admin:
        keyboard.append([InlineKeyboardButton(get_text(uid, "admin_panel"), callback_data=CallbackData.ADMIN_PANEL)])
    valid_keyboard = []
    for row in keyboard:
        if row and all(isinstance(btn, InlineKeyboardButton) for btn in row):
            valid_keyboard.append(row)
    if not valid_keyboard:
        valid_keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    if query:
        await safe_edit_markdown(query, title, reply_markup=InlineKeyboardMarkup(valid_keyboard))
    else:
        await safe_send_markdown(context.bot, uid, title, reply_markup=InlineKeyboardMarkup(valid_keyboard))

async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or ""
    await db_register_user(user_id)
    await db_update_user_cache(user_id, username, first_name)
    if context.args and context.args[0].startswith("ref_"):
        referral_code = context.args[0].replace("ref_", "")
        referrer_id = await db_get_user_by_referral_code(referral_code)
        if referrer_id and referrer_id != user_id:
            success = await db_add_referral(referrer_id, user_id)
            if success:
                reward_days = await db_auto_reward_referral(referrer_id, user_id)
                try:
                    await context.bot.send_message(chat_id=referrer_id, text=f"🎉 **تهانينا!**\nقام {first_name} بالاشتراك باستخدام رابط إحالتك!\nتم إضافة {reward_days} أيام إلى اشتراكك 🎁", parse_mode="MarkdownV2")
                except:
                    pass
                welcome_points = await db_get_welcome_bonus_points()
                if welcome_points > 0:
                    level_data = await db_get_user_level(user_id)
                    await db_update_user_level(user_id, level_data["points"] + welcome_points, level_data["level"])
    await main_menu_callback(update, context)

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await main_menu_callback(update, context)

async def cancel_session_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    context.user_data.pop(f"session_{uid}", None)
    context.user_data.pop(f"session_target_{uid}", None)
    context.user_data.pop("state", None)
    if query:
        await query.edit_message_text(get_text(uid, "cancelled"))
    else:
        await context.bot.send_message(chat_id=uid, text=get_text(uid, "cancelled"))
    await main_menu_callback(update, context)

async def add_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    context.user_data["state"] = "WAITING_CHANNEL_ID"
    msg = get_text(uid, "send_channel_id")
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def my_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    channels = await db_get_channels(uid)
    if not channels:
        msg = get_text(uid, "no_channels_list")
        if query:
            await query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return
    kb = []
    for ch in channels:
        ch_db_id, ch_tele_id, ch_name, banned = ch
        display = ch_name if ch_name != ch_tele_id else ch_tele_id
        kb.append([InlineKeyboardButton(f"📢 {display}", callback_data=f"{CallbackData.CHANNELS_SELECT_PREFIX}{ch_db_id}"), InlineKeyboardButton(get_text(uid, "channel_stats"), callback_data=f"{CallbackData.CHANNEL_STATS}:{ch_db_id}"), InlineKeyboardButton(get_text(uid, "delete_channel"), callback_data=f"{CallbackData.CHANNELS_DELETE_PREFIX}{ch_db_id}")])
    kb.append([InlineKeyboardButton(get_text(uid, "add_channel"), callback_data=CallbackData.CHANNELS_ADD)])
    kb.append([InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)])
    if query:
        await query.edit_message_text(get_text(uid, "channels_list"), reply_markup=InlineKeyboardMarkup(kb))
    else:
        await safe_send_markdown(context.bot, uid, get_text(uid, "channels_list"), reply_markup=InlineKeyboardMarkup(kb))

async def delete_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get("delete_channel_id")
    if not ch_db_id:
        return
    if await db_delete_channel_by_id(uid, ch_db_id):
        if query:
            await query.edit_message_text(get_text(uid, "channel_deleted"))
        else:
            await update.message.reply_text(get_text(uid, "channel_deleted"))
        await my_channels_callback(update, context)
    else:
        if query:
            await query.answer(get_text(uid, "delete_failed"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "delete_failed"))

async def select_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    await db_set_active_channel(uid, ch_db_id)
    context.user_data["active_channel"] = ch_db_id
    await invalidate_user_cache(uid)
    await main_menu_callback(update, context)

async def add_15_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = context.user_data.get("active_channel") or await db_get_active_channel(uid)
    if not active:
        if query:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
        else:
            await update.message.reply_text("⚠️ اختر قناة أولاً")
        return
    unpublished_count = await db_unpublished_count(active)
    if unpublished_count >= MAX_UNPUBLISHED_POSTS:
        if query:
            await query.edit_message_text(f"⚠️ لقد تجاوزت الحد الأقصى للمنشورات غير المنشورة ({MAX_UNPUBLISHED_POSTS}).\nقم بنشر بعض المنشورات أولاً.")
        else:
            await update.message.reply_text(f"⚠️ لقد تجاوزت الحد الأقصى للمنشورات غير المنشورة ({MAX_UNPUBLISHED_POSTS}).\nقم بنشر بعض المنشورات أولاً.")
        return
    context.user_data[f"session_{uid}"] = []
    context.user_data[f"session_target_{uid}"] = min(15, MAX_UNPUBLISHED_POSTS - unpublished_count)
    context.user_data["state"] = "ADDING_POSTS"
    cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.CANCEL_SESSION)]])
    msg = f"📥 أرسل المنشورات (نصوص أو صور أو فيديوهات أو مستندات)\nالحد الأقصى المسموح: {MAX_UNPUBLISHED_POSTS - unpublished_count} منشور"
    if query:
        await query.edit_message_text(msg, reply_markup=cancel_kb)
    else:
        await update.message.reply_text(msg, reply_markup=cancel_kb)

async def publish_one_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = context.user_data.get("active_channel") or await db_get_active_channel(uid)
    if not active:
        if query:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
        else:
            await update.message.reply_text("⚠️ اختر قناة أولاً")
        return
    post = await db_get_next_post(active)
    if not post:
        if query:
            await query.edit_message_text(get_text(uid, "no_posts"))
        else:
            await update.message.reply_text(get_text(uid, "no_posts"))
        return
    ch_info = await db_get_channel_info(active)
    translation_lang = await get_user_translation_language(uid)
    final_text = post["text"]
    if translation_lang != "off" and final_text:
        try:
            translated = await translate_text(final_text, translation_lang)
            if translated and translated != final_text:
                final_text = f"{final_text}\n\n🌐 {translated}"
        except:
            pass
    try:
        if post["media_type"] == "photo" and post["media_file_id"]:
            await context.bot.send_photo(ch_info[0], post["media_file_id"], caption=final_text if final_text else None)
        elif post["media_type"] == "video" and post["media_file_id"]:
            await context.bot.send_video(ch_info[0], post["media_file_id"], caption=final_text if final_text else None)
        elif post["media_type"] == "document" and post["media_file_id"]:
            await context.bot.send_document(ch_info[0], post["media_file_id"], caption=final_text if final_text else None)
        elif post["media_type"] == "audio" and post["media_file_id"]:
            await context.bot.send_audio(ch_info[0], post["media_file_id"], caption=final_text if final_text else None)
        elif post["media_type"] == "voice" and post["media_file_id"]:
            await context.bot.send_voice(ch_info[0], post["media_file_id"], caption=final_text if final_text else None)
        elif post["media_type"] == "animation" and post["media_file_id"]:
            await context.bot.send_animation(ch_info[0], post["media_file_id"], caption=final_text if final_text else None)
        else:
            await context.bot.send_message(ch_info[0], final_text, parse_mode=None)
        await db_mark_published(post["id"])
        await db_set_last_publish(active, utc_now())
        await db_update_next_publish_date(active)
        if query:
            await query.edit_message_text(get_text(uid, "post_published"))
        else:
            await update.message.reply_text(get_text(uid, "post_published"))
    except Exception as e:
        if query:
            await query.edit_message_text(get_text(uid, "publish_error").format(str(e)[:100]))
        else:
            await update.message.reply_text(get_text(uid, "publish_error").format(str(e)[:100]))
    await main_menu_callback(update, context)

async def my_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = context.user_data.get("active_channel") or await db_get_active_channel(uid)
    if not active:
        if query:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
        else:
            await update.message.reply_text("⚠️ اختر قناة أولاً")
        return
    posts = await db_get_user_posts_for_channel(active, limit=15)
    if not posts:
        if query:
            await query.edit_message_text(get_text(uid, "no_posts"))
        else:
            await update.message.reply_text(get_text(uid, "no_posts"))
        return
    msg = get_text(uid, "my_posts_title") + "\n"
    kb_buttons = []
    for idx, (pid, ptext, media_type) in enumerate(posts[:10], 1):
        short = re.sub("<[^>]+>", "", ptext)[:80]
        media_icon = "🖼️" if media_type == "photo" else "🎬" if media_type == "video" else "📝" if media_type == "text" else "📄"
        msg += f"{idx}. {media_icon} {short}...\n🆔 {pid}\n\n"
        kb_buttons.append([InlineKeyboardButton(f"🗑️ حذف #{pid}", callback_data=f"{CallbackData.POSTS_DELETE_SINGLE_PREFIX}{pid}_{active}")])
    kb_buttons.append([InlineKeyboardButton("🗑️ حذف الكل", callback_data=f"{CallbackData.POSTS_CONFIRM_CLEAR_ALL_PREFIX}{active}")])
    kb_buttons.append([InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)])
    if query:
        await safe_edit_markdown(query, msg, reply_markup=InlineKeyboardMarkup(kb_buttons))
    else:
        await safe_send_markdown(context.bot, uid, msg, reply_markup=InlineKeyboardMarkup(kb_buttons))

async def delete_single_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    parts = query.data.split(":")[-1].split("_") if query else context.user_data.get("delete_post_data", "").split("_")
    if len(parts) >= 2:
        post_id = int(parts[0])
        active = int(parts[1])
        if await db_delete_single_post(post_id, uid, active):
            if query:
                await query.answer("✅ تم حذف المنشور", show_alert=True)
            else:
                await update.message.reply_text("✅ تم حذف المنشور")
            await my_posts_callback(update, context)
        else:
            if query:
                await query.answer("❌ فشل الحذف", show_alert=True)
            else:
                await update.message.reply_text("❌ فشل الحذف")

async def confirm_clear_all_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = int(query.data.split(":")[-1]) if query else context.user_data.get("clear_all_posts_id")
    if not active:
        return
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ نعم", callback_data=f"{CallbackData.POSTS_CLEAR_ALL_PREFIX}{active}"), InlineKeyboardButton("❌ لا", callback_data=CallbackData.BACK)]])
    if query:
        await query.edit_message_text(get_text(uid, "confirm_delete"), reply_markup=kb)
    else:
        await update.message.reply_text(get_text(uid, "confirm_delete"), reply_markup=kb)

async def clear_all_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = int(query.data.split(":")[-1]) if query else context.user_data.get("clear_all_posts_id")
    if not active:
        return
    async def _clear_posts(conn):
        await conn.execute("DELETE FROM posts WHERE channel_db_id=?", (active,))
        await conn.commit()
    await execute_db(_clear_posts)
    if query:
        await query.answer(get_text(uid, "deleted_all"), show_alert=True)
    else:
        await update.message.reply_text(get_text(uid, "deleted_all"))
    await main_menu_callback(update, context)

async def recycle_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = context.user_data.get("active_channel") or await db_get_active_channel(uid)
    if active:
        await db_reset_posts_to_unpublished(active, uid)
        if query:
            await query.edit_message_text(get_text(uid, "recycled"))
        else:
            await update.message.reply_text(get_text(uid, "recycled"))
    else:
        if query:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
        else:
            await update.message.reply_text("⚠️ اختر قناة أولاً")
    await main_menu_callback(update, context)

async def my_pending_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    unpublished = await db_get_user_unpublished_posts(uid)
    total = await db_get_user_total_posts(uid)
    text = get_text(uid, "pending_stats").format(unpublished, total)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def my_full_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    channels = await db_get_user_channels_count(uid)
    total = await db_get_user_total_posts(uid)
    unpublished = await db_get_user_unpublished_posts(uid)
    groups = await db_get_user_groups_count(uid)
    auto = get_text(uid, "auto_on") if await db_auto_status(uid) else get_text(uid, "auto_off")
    text = get_text(uid, "stats").format(channels, total, unpublished, groups, auto)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def my_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    groups = await db_get_user_groups(uid)
    if not groups:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ أضف البوت", url=f"https://t.me/{BOT_USERNAME}?startgroup")], [InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS)], [InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]])
        msg = "📭 لا توجد مجموعات مسجلة\n\nأضف البوت إلى مجموعة وستظهر هنا."
        if query:
            await safe_edit_markdown(query, msg, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, msg, reply_markup=kb)
        return
    keyboard = []
    for chat_id, chat_name, username, banned in groups:
        display_name = chat_name[:28] + "..." if len(chat_name) > 31 else chat_name
        status_icon = "⛔" if banned else "✅"
        keyboard.append([InlineKeyboardButton(f"{status_icon} {display_name}", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")])
        keyboard.append([InlineKeyboardButton("🔐 الأمان", callback_data=f"{CallbackData.SECURITY_SELECT_GROUP}{chat_id}"), InlineKeyboardButton("📜 السجل", callback_data=f"{CallbackData.GROUP_ACTION_LOG}:{chat_id}"), InlineKeyboardButton("⚙️ متقدم", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}")])
        is_locked = await is_chat_locked(chat_id)
        lock_label = "🔒 قفل" if not is_locked else "🔓 فتح"
        lock_callback = f"{CallbackData.PANEL_LOCK_PREFIX}{chat_id}" if not is_locked else f"{CallbackData.PANEL_UNLOCK_PREFIX}{chat_id}"
        can_delete = await db_is_hidden_owner(chat_id, uid) or uid == PRIMARY_OWNER_ID
        if can_delete:
            keyboard.append([InlineKeyboardButton(lock_label, callback_data=lock_callback), InlineKeyboardButton("🗑️ حذف", callback_data=f"delete_group:{chat_id}")])
        else:
            keyboard.append([InlineKeyboardButton(lock_label, callback_data=lock_callback)])
        keyboard.append([InlineKeyboardButton("─" * 20, callback_data="noop")])
    keyboard.append([InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS), InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "👥 **مجموعاتي**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر مجموعة للتحكم بها:\n\n✅ = نشطة  |  ⛔ = محظورة"
    if query:
        await safe_edit_markdown(query, text, reply_markup=reply_markup)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=reply_markup)

async def group_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("group_chat_id")
    if not chat_id:
        if query:
            await query.edit_message_text("❌ لم يتم تحديد المجموعة")
        else:
            await update.message.reply_text("❌ لم يتم تحديد المجموعة")
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    settings = await db_get_security_settings(chat_id)
    async def _get_group_name(conn):
        cur = await conn.execute("SELECT chat_name FROM bot_groups WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        name = row[0] if row else str(chat_id)
        if len(name) > 50:
            name = name[:47] + "..."
        return name
    gname = await execute_db(_get_group_name)
    text = f"⚙️ **لوحة تحكم المجموعة: {gname}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🔗 حذف الروابط: {'✅' if settings['links'] else '❌'}\n"
    text += f"@ حذف المعرفات: {'✅' if settings['mentions'] else '❌'}\n"
    text += f"🚫 كلمات محظورة: {'✅' if settings.get('delete_banned_words', False) else '❌'}\n"
    text += f"⏱️ وضع بطيء: {'✅' if settings.get('slow_mode', False) else '❌'}\n"
    text += f"🎯 رسالة ترحيب: {'✅' if settings.get('welcome_enabled', False) else '❌'}\n"
    text += f"👋 رسالة وداع: {'✅' if settings.get('goodbye_enabled', False) else '❌'}\n"
    text += f"🔊 رسالة تحذير: {'✅' if settings['warn'] else '❌'}\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"⚖️ **العقوبة التلقائية:** {'طرد' if settings.get('auto_penalty') == 'kick' else 'حظر' if settings.get('auto_penalty') == 'ban' else 'كتم' if settings.get('auto_penalty') == 'mute' else 'لا شيء'}\n"
    if settings.get('auto_penalty') == 'mute' and settings.get('auto_mute_duration'):
        minutes = settings.get('auto_mute_duration')
        if minutes == -1:
            text += f"   مدة الكتم: دائم\n"
        elif minutes < 60:
            text += f"   مدة الكتم: {minutes} دقيقة\n"
        elif minutes < 1440:
            text += f"   مدة الكتم: {minutes // 60} ساعة\n"
        else:
            text += f"   مدة الكتم: {minutes // 1440} يوم\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📌 **اختر الإجراء المناسب:**"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 حذف الروابط", callback_data=f"{CallbackData.SECURITY_LINKS_PREFIX}{chat_id}"), InlineKeyboardButton("@ حذف المعرفات", callback_data=f"{CallbackData.SECURITY_MENTIONS_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🚫 كلمات محظورة", callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}"), InlineKeyboardButton("⏱️ الوضع البطيء", callback_data=f"{CallbackData.SECURITY_SLOWMODE_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🎯 الترحيب", callback_data=f"{CallbackData.SECURITY_WELCOME_PREFIX}{chat_id}"), InlineKeyboardButton("👋 الوداع", callback_data=f"{CallbackData.SECURITY_GOODBYE_PREFIX}{chat_id}")],
        [InlineKeyboardButton("⚖️ تحديد العقوبة", callback_data=f"{CallbackData.PENALTY_MENU}:{chat_id}"), InlineKeyboardButton("📝 إعدادات الردود", callback_data=CallbackData.ADMIN_AUTO_REPLY)],
        [InlineKeyboardButton("🛠️ إجراءات متقدمة", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}")],
        [InlineKeyboardButton("📜 سجل الإجراءات", callback_data=f"{CallbackData.GROUP_ACTION_LOG}:{chat_id}")],
        [InlineKeyboardButton("🔙 إغلاق", callback_data=CallbackData.SECURITY_CLOSE)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    auto = await db_auto_status(uid)
    auto_btn = get_text(uid, "disabled") if auto else get_text(uid, "enabled")
    recycle = await db_get_auto_recycle(uid)
    recycle_btn = get_text(uid, "enabled") if recycle else get_text(uid, "disabled")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"{auto_btn} النشر التلقائي", callback_data=CallbackData.SETTINGS_TOGGLE_AUTO_PUBLISH)], [InlineKeyboardButton(f"♻️ إعادة التدوير: {recycle_btn}", callback_data=CallbackData.SETTINGS_TOGGLE_AUTO_RECYCLE)], [InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]])
    if query:
        await query.edit_message_text(get_text(uid, "settings"), reply_markup=kb)
    else:
        await update.message.reply_text(get_text(uid, "settings"), reply_markup=kb)

async def toggle_auto_publish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    cur = await db_auto_status(uid)
    await db_set_auto(uid, not cur)
    status = get_text(uid, "enabled") if not cur else get_text(uid, "disabled")
    if query:
        await query.edit_message_text(get_text(uid, "auto_toggled").format(status))
    else:
        await update.message.reply_text(get_text(uid, "auto_toggled").format(status))
    await main_menu_callback(update, context)

async def toggle_auto_recycle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    cur = await db_get_auto_recycle(uid)
    new_status = not cur
    await db_set_auto_recycle(uid, new_status)
    status = get_text(uid, "enabled") if new_status else get_text(uid, "disabled")
    if query:
        await query.edit_message_text(f"✅ تم تغيير إعادة التدوير التلقائي إلى: {status}")
    else:
        await update.message.reply_text(f"✅ تم تغيير إعادة التدوير التلقائي إلى: {status}")
    await settings_menu_callback(update, context)

async def schedule_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    parts = query.data.split(":") if query else context.user_data.get("schedule_data", "").split(":")
    if len(parts) >= 3:
        ch_db_id = int(parts[-1])
    else:
        ch_db_id = context.user_data.get("active_channel") or await db_get_active_channel(uid)
    if not ch_db_id:
        if query:
            await query.edit_message_text("⚠️ يرجى اختيار قناة أولاً")
        else:
            await update.message.reply_text("⚠️ يرجى اختيار قناة أولاً")
        return
    schedule = await db_get_schedule(ch_db_id)
    if schedule["type"] == "interval_minutes":
        txt = get_text(uid, "interval_minutes").format(schedule["interval_minutes"])
    elif schedule["type"] == "interval_hours":
        txt = get_text(uid, "interval_hours").format(schedule["interval_hours"])
    elif schedule["type"] == "interval_days":
        txt = get_text(uid, "interval_days").format(schedule["interval_days"])
    elif schedule["type"] == "days":
        days = json.loads(schedule["days_of_week"])
        day_names = [get_text(uid, "monday"), get_text(uid, "tuesday"), get_text(uid, "wednesday"), get_text(uid, "thursday"), get_text(uid, "friday"), get_text(uid, "saturday"), get_text(uid, "sunday")]
        txt = get_text(uid, "days_week").format(", ".join([day_names[d] for d in days]) if days else get_text(uid, "nothing"))
    elif schedule["type"] == "cron":
        txt = f"⏰ CRON: {schedule.get('cron_expression', 'غير محدد')}"
    else:
        dates = json.loads(schedule["specific_dates"])
        txt = get_text(uid, "specific_dates").format(", ".join(dates) if dates else get_text(uid, "nothing"))
    pub_time = schedule.get("publish_time", "00:00")
    txt += f"\n🕐 وقت النشر: {pub_time} (بتوقيت مكة)"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 دقائق", callback_data=f"{CallbackData.SCHEDULE_SET_INTERVAL_MINUTES_PREFIX}{ch_db_id}"), InlineKeyboardButton("🕒 ساعات", callback_data=f"{CallbackData.SCHEDULE_SET_INTERVAL_HOURS_PREFIX}{ch_db_id}")],
        [InlineKeyboardButton("📆 أيام", callback_data=f"{CallbackData.SCHEDULE_SET_INTERVAL_DAYS_PREFIX}{ch_db_id}"), InlineKeyboardButton("📅 أيام أسبوع", callback_data=f"{CallbackData.SCHEDULE_SET_DAYS_PREFIX}{ch_db_id}")],
        [InlineKeyboardButton("🗓️ تواريخ محددة", callback_data=f"{CallbackData.SCHEDULE_SET_DATES_PREFIX}{ch_db_id}"), InlineKeyboardButton("⏰ وقت النشر", callback_data=f"{CallbackData.SCHEDULE_SET_PUBLISH_TIME_PREFIX}{ch_db_id}")],
        [InlineKeyboardButton("⏱️ CRON", callback_data=f"schedule:set_cron:{ch_db_id}")],
        [InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, get_text(uid, "schedule_settings").format(txt), reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, get_text(uid, "schedule_settings").format(txt), reply_markup=kb)

async def set_interval_minutes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get("schedule_ch_id")
    if not ch_db_id:
        return
    context.user_data["state"] = "WAITING_INTERVAL_MINUTES"
    context.user_data["schedule_ch_id"] = ch_db_id
    if query:
        await query.edit_message_text(get_text(uid, "send_minutes"))
    else:
        await update.message.reply_text(get_text(uid, "send_minutes"))

async def set_interval_hours_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get("schedule_ch_id")
    if not ch_db_id:
        return
    context.user_data["state"] = "WAITING_INTERVAL_HOURS"
    context.user_data["schedule_ch_id"] = ch_db_id
    if query:
        await query.edit_message_text(get_text(uid, "send_hours"))
    else:
        await update.message.reply_text(get_text(uid, "send_hours"))

async def set_interval_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get("schedule_ch_id")
    if not ch_db_id:
        return
    context.user_data["state"] = "WAITING_INTERVAL_DAYS"
    context.user_data["schedule_ch_id"] = ch_db_id
    if query:
        await query.edit_message_text(get_text(uid, "send_days"))
    else:
        await update.message.reply_text(get_text(uid, "send_days"))

async def set_cron_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get("schedule_ch_id")
    if not ch_db_id:
        return
    context.user_data["state"] = "WAITING_CRON"
    context.user_data["schedule_ch_id"] = ch_db_id
    msg = "⏱️ **إعداد CRON**\n\nأرسل تعبير CRON (مثال: `0 12 * * *` للنشر يومياً الساعة 12:00)\n\nالشرح:\n• دقيقة (0-59)\n• ساعة (0-23)\n• يوم (1-31)\n• شهر (1-12)\n• يوم أسبوع (0-6)"
    if query:
        await query.edit_message_text(msg, parse_mode="MarkdownV2")
    else:
        await update.message.reply_text(msg, parse_mode="MarkdownV2")

async def set_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get("schedule_ch_id")
    if not ch_db_id:
        return
    context.user_data["selected_days_ch"] = ch_db_id
    context.user_data["selected_days"] = []
    context.user_data["state"] = "SELECTING_DAYS"
    day_names = [get_text(uid, "monday"), get_text(uid, "tuesday"), get_text(uid, "wednesday"), get_text(uid, "thursday"), get_text(uid, "friday"), get_text(uid, "saturday"), get_text(uid, "sunday")]
    kb_buttons = []
    for i in range(0, 7, 3):
        row = []
        for j in range(3):
            if i + j < 7:
                day_index = i + j
                name = day_names[day_index]
                row.append(InlineKeyboardButton(f"{name}", callback_data=f"{CallbackData.SCHEDULE_DAY_SELECT_PREFIX}{day_index}"))
        if row:
            kb_buttons.append(row)
    kb_buttons.append([InlineKeyboardButton("✔️ حفظ", callback_data=CallbackData.SCHEDULE_SAVE_DAYS), InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)])
    if query:
        await query.edit_message_text("اختر أيام النشر (بتوقيت مكة):", reply_markup=InlineKeyboardMarkup(kb_buttons))
    else:
        await update.message.reply_text("اختر أيام النشر (بتوقيت مكة):", reply_markup=InlineKeyboardMarkup(kb_buttons))

async def set_dates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get("schedule_ch_id")
    if not ch_db_id:
        return
    context.user_data["state"] = "WAITING_DATES"
    context.user_data["schedule_ch_id"] = ch_db_id
    if query:
        await query.edit_message_text(get_text(uid, "send_dates"))
    else:
        await update.message.reply_text(get_text(uid, "send_dates"))

async def set_publish_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get("schedule_ch_id")
    if not ch_db_id:
        return
    context.user_data["state"] = "WAITING_PUBLISH_TIME"
    context.user_data["schedule_ch_id"] = ch_db_id
    if query:
        await query.edit_message_text(get_text(uid, "send_time"))
    else:
        await update.message.reply_text(get_text(uid, "send_time"))

async def day_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    day = int(query.data.split(":")[-1]) if query else context.user_data.get("selected_day")
    if day is None:
        return
    selected = context.user_data.get("selected_days", [])
    if day in selected:
        selected.remove(day)
    else:
        selected.append(day)
    context.user_data["selected_days"] = selected
    day_names = [get_text(uid, "monday"), get_text(uid, "tuesday"), get_text(uid, "wednesday"), get_text(uid, "thursday"), get_text(uid, "friday"), get_text(uid, "saturday"), get_text(uid, "sunday")]
    kb_buttons = []
    for i in range(0, 7, 3):
        row = []
        for j in range(3):
            if i + j < 7:
                day_index = i + j
                name = day_names[day_index]
                mark = "✅ " if day_index in selected else ""
                row.append(InlineKeyboardButton(f"{mark}{name}", callback_data=f"{CallbackData.SCHEDULE_DAY_SELECT_PREFIX}{day_index}"))
        if row:
            kb_buttons.append(row)
    kb_buttons.append([InlineKeyboardButton("✔️ حفظ", callback_data=CallbackData.SCHEDULE_SAVE_DAYS), InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)])
    if query:
        await query.edit_message_text("اختر أيام النشر (بتوقيت مكة):", reply_markup=InlineKeyboardMarkup(kb_buttons))
    else:
        await update.message.reply_text("اختر أيام النشر (بتوقيت مكة):", reply_markup=InlineKeyboardMarkup(kb_buttons))

async def save_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch = context.user_data.get("selected_days_ch")
    if ch:
        days_json = json.dumps(context.user_data.get("selected_days", []))
        await db_save_schedule(ch, "days", days_of_week=days_json)
        await db_set_next_publish_date(ch, None)
        context.user_data.pop("selected_days_ch", None)
        context.user_data.pop("selected_days", None)
        context.user_data.pop("state", None)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]])
        if query:
            await safe_edit_markdown(query, get_text(uid, "days_saved"), reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, get_text(uid, "days_saved"), reply_markup=kb)
    else:
        if query:
            await query.edit_message_text(get_text(uid, "error"))
        else:
            await update.message.reply_text(get_text(uid, "error"))

async def security_links_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("security_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    settings = await db_get_security_settings(chat_id)
    settings["links"] = not settings["links"]
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, "updated"))
    else:
        await update.message.reply_text(get_text(uid, "updated"))
    await group_settings_callback(update, context)

async def security_mentions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("security_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    settings = await db_get_security_settings(chat_id)
    settings["mentions"] = not settings["mentions"]
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, "updated"))
    else:
        await update.message.reply_text(get_text(uid, "updated"))
    await group_settings_callback(update, context)

async def security_slowmode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("security_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    settings = await db_get_security_settings(chat_id)
    settings["slow_mode"] = not settings["slow_mode"]
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, "updated"))
    else:
        await update.message.reply_text(get_text(uid, "updated"))
    await group_settings_callback(update, context)

async def security_banned_words_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("security_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    context.user_data["banned_words_chat_id"] = chat_id
    msg = "🚫 إدارة الكلمات المحظورة للمجموعة"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ إضافة كلمة", callback_data=f"{CallbackData.BANNED_WORDS_ADD_PREFIX}{chat_id}"), InlineKeyboardButton("📋 عرض الكلمات", callback_data=f"{CallbackData.BANNED_WORDS_LIST_PREFIX}{chat_id}")], [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=f"{CallbackData.BANNED_WORDS_REMOVE_PREFIX}{chat_id}"), InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
    if query:
        await query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

async def security_welcome_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("security_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    settings = await db_get_security_settings(chat_id)
    settings["welcome_enabled"] = not settings["welcome_enabled"]
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, "updated"))
    else:
        await update.message.reply_text(get_text(uid, "updated"))
    await group_settings_callback(update, context)

async def security_goodbye_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("security_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    settings = await db_get_security_settings(chat_id)
    settings["goodbye_enabled"] = not settings["goodbye_enabled"]
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, "updated"))
    else:
        await update.message.reply_text(get_text(uid, "updated"))
    await group_settings_callback(update, context)

async def security_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.message.delete()

async def banned_words_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("banned_words_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, "admin_only"))
        return
    context.user_data["state"] = "WAITING_GROUP_BANNED_WORD"
    context.user_data["banned_words_chat_id"] = chat_id
    msg = "➕ أرسل الكلمة التي تريد إضافتها للكلمات المحظورة:"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def banned_words_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("banned_words_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, "admin_only"))
        return
    words = await db_get_banned_words(chat_id)
    if not words:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}")]])
        if query:
            await query.edit_message_text("📭 لا توجد كلمات محظورة في هذه المجموعة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد كلمات محظورة في هذه المجموعة.", reply_markup=kb)
        return
    text = "🚫 **الكلمات المحظورة في المجموعة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for word, added_by, added_at in words[:20]:
        text += f"• `{word}` (أضيف بواسطة {added_by})\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}")]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def banned_words_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("banned_words_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, "admin_only"))
        return
    context.user_data["state"] = "WAITING_REMOVE_GROUP_BANNED_WORD"
    context.user_data["banned_words_chat_id"] = chat_id
    msg = "🗑️ أرسل الكلمة التي تريد حذفها من الكلمات المحظورة:"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def penalty_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("security_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    msg = "⚖️ **اختر العقوبة التلقائية:**\n\nسيتم تطبيق هذه العقوبة عند مخالفة قواعد الحماية:"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔴 طرد", callback_data=f"{CallbackData.PENALTY_KICK}:{chat_id}"), InlineKeyboardButton("🛑 حظر", callback_data=f"{CallbackData.PENALTY_BAN}:{chat_id}")], [InlineKeyboardButton("🔇 كتم", callback_data=f"{CallbackData.PENALTY_MUTE}:{chat_id}"), InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
    if query:
        await query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

async def penalty_kick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("security_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    await db_set_security_settings(chat_id, auto_penalty="kick")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
    if query:
        await query.edit_message_text("✅ تم تعيين العقوبة التلقائية إلى: **طرد**", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم تعيين العقوبة التلقائية إلى: **طرد**", reply_markup=kb)

async def penalty_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("security_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    await db_set_security_settings(chat_id, auto_penalty="ban")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
    if query:
        await query.edit_message_text("✅ تم تعيين العقوبة التلقائية إلى: **حظر**", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم تعيين العقوبة التلقائية إلى: **حظر**", reply_markup=kb)

async def penalty_mute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("security_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    context.user_data["penalty_chat_id"] = chat_id
    msg = "🔇 **اختر مدة الكتم:**"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏱️ 5 دقائق", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_5}:{chat_id}"), InlineKeyboardButton("⏱️ 30 دقيقة", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_30}:{chat_id}")], [InlineKeyboardButton("⏱️ 1 ساعة", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_60}:{chat_id}"), InlineKeyboardButton("⏱️ 12 ساعة", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_720}:{chat_id}")], [InlineKeyboardButton("📆 يوم", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_1440}:{chat_id}"), InlineKeyboardButton("📆 أسبوع", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_10080}:{chat_id}")], [InlineKeyboardButton("🔇 كتم دائم", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_PERMANENT}:{chat_id}"), InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.PENALTY_MENU}:{chat_id}")]])
    if query:
        await query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

async def penalty_mute_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    data_parts = query.data.split(":") if query else context.user_data.get("penalty_mute_data", "").split(":")
    if len(data_parts) == 3:
        duration = data_parts[1]
        chat_id = int(data_parts[2])
        uid = update.effective_user.id
        if not await is_authorized_in_group(context.bot, chat_id, uid):
            if query:
                await query.answer(get_text(uid, "admin_only"), show_alert=True)
            else:
                await update.message.reply_text(get_text(uid, "admin_only"))
            return
        if duration == "permanent":
            minutes = -1
            text = "دائم"
        else:
            minutes = int(duration)
            if minutes < 60:
                text = f"{minutes} دقيقة"
            elif minutes < 1440:
                text = f"{minutes // 60} ساعة"
            else:
                text = f"{minutes // 1440} يوم"
        await db_set_security_settings(chat_id, auto_penalty="mute", auto_mute_duration=minutes)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
        if query:
            await query.edit_message_text(f"✅ تم تعيين العقوبة التلقائية إلى: **كتم {text}**", reply_markup=kb)
        else:
            await update.message.reply_text(f"✅ تم تعيين العقوبة التلقائية إلى: **كتم {text}**", reply_markup=kb)

async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, "back"), callback_data=CallbackData.BACK)]])
    if query:
        await safe_edit_markdown(query, get_text(user_id, "help"), reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, get_text(user_id, "help"), reply_markup=keyboard)

async def support_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    context.user_data["support_mode"] = True
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📝 كتابة تذكرة", callback_data=CallbackData.SUPPORT_TICKET)], [InlineKeyboardButton("❓ المساعدة", callback_data=CallbackData.SUPPORT_HELP)], [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
    text = get_text(user_id, "support_welcome")
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def support_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.SUPPORT_MENU)]])
    text = get_text(user_id, "support_help")
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def support_ticket_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    context.user_data["support_mode"] = True
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data=CallbackData.SUPPORT_MENU)]])
    text = "📝 **اكتب رسالتك** (سيتم إرسالها كتذكرة دعم)\nيمكنك إلغاء العملية بالضغط على الزر أدناه."
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def trial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if await db_has_used_trial(uid):
        if query:
            await query.edit_message_text(get_text(uid, "trial_used"))
        else:
            await update.message.reply_text(get_text(uid, "trial_used"))
        return
    if await db_has_active_subscription(uid):
        if query:
            await query.edit_message_text(get_text(uid, "already_subscribed"))
        else:
            await update.message.reply_text(get_text(uid, "already_subscribed"))
        return
    await db_activate_trial(uid)
    if query:
        await query.edit_message_text(get_text(uid, "trial"))
    else:
        await update.message.reply_text(get_text(uid, "trial"))
    await main_menu_callback(update, context)

async def subscribe_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if await db_has_active_subscription(uid):
        days = await db_get_subscription_days_left(uid)
        msg = f"✅ اشتراكك مفعل، متبقي {days} يوم\nشكراً لدعمك ❤️"
        if query:
            await query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⭐ 1 يوم - 5 نجوم", callback_data=CallbackData.BUY_SUBSCRIPTION_1), InlineKeyboardButton("⭐ 2 يوم - 9 نجوم", callback_data=CallbackData.BUY_SUBSCRIPTION_2)], [InlineKeyboardButton("⭐ شهر (30 يوم) - 50 نجمة", callback_data=CallbackData.BUY_SUBSCRIPTION_30), InlineKeyboardButton("⭐ 3 أشهر (90 يوم) - 120 نجمة", callback_data=CallbackData.BUY_SUBSCRIPTION_90)], [InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]])
    text = get_text(uid, "subscribe")
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)

async def buy_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, days: int, price: int, title: str):
    query = update.callback_query
    user_id = update.effective_user.id
    try:
        await context.bot.send_invoice(chat_id=user_id, title=title, description=f"اشتراك {days} يوم", payload=f"sub_{days}_{price}", currency="XTR", prices=[LabeledPrice(label=f"اشتراك {days} يوم", amount=price)], need_name=False, need_phone_number=False, need_email=False, need_shipping_address=False, is_flexible=False)
    except Exception as e:
        if "Stars" in str(e):
            if query:
                await query.edit_message_text("❌ الدفع بالنجوم غير مفعل حالياً، استخدم /trial")
            else:
                await update.message.reply_text("❌ الدفع بالنجوم غير مفعل حالياً، استخدم /trial")
        else:
            if query:
                await query.edit_message_text(f"❌ خطأ: {str(e)[:100]}")
            else:
                await update.message.reply_text(f"❌ خطأ: {str(e)[:100]}")

async def buy_subscription_1_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    await buy_subscription_callback(update, context, 1, 5, "اشتراك 1 يوم")

async def buy_subscription_2_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    await buy_subscription_callback(update, context, 2, 9, "اشتراك 2 يوم")

async def buy_subscription_30_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    await buy_subscription_callback(update, context, 30, 50, "اشتراك شهر")

async def buy_subscription_90_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    await buy_subscription_callback(update, context, 90, 120, "اشتراك 3 أشهر")

async def developer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    text = f"""👑 **معلومات المطور**
━━━━━━━━━━━━━━━━━━━━━━
🤖 **البوت:** {BOT_NAME}
📦 **الإصدار:** 19.3.0
👨‍💻 **المطور:** @RelaxMgr

🔐 **الميزات الأمنية المتقدمة:**
• دعم كامل للمشرفين المخفيين (Anonymous)
• فصل ذكي للصلاحيات بين الخاص والمجموعة
• أمر /update_admins لتحديث المشرفين
• نظام كشف النشاط المشبوه
• تخزين مؤقت محسن مع تنظيف تلقائي
• Pool اتصالات قاعدة البيانات
• نظام Rate Limiting متقدم
• مصادقة ثنائية (2FA)
• تشفير قاعدة البيانات بكلمة مرور (PBKDF2)
• نسخ احتياطي تدريجي وضغط محسن
• Health Check متقدم
• مراقبة الذاكرة التلقائية
• تنظيف الكاش التلقائي لتسريع الردود

📞 **طرق التواصل:**
✅ **تيليجرام:** @RelaxMgr
✅ **البوت:** @{BOT_USERNAME}"""
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📩 تواصل مع المطور", url=f"https://t.me/RelaxMgr")], [InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def updates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    updates_channel = await db_get_updates_channel()
    if updates_channel:
        text = f"""📢 **قناة التحديثات**
━━━━━━━━━━━━━━━━━━━━━━
📌 القناة: @{updates_channel}

📢 تابع القناة لمعرفة آخر التحديثات:
• ميزات جديدة ✨
• تحسينات الأداء ⚡
• إصلاحات الأخطاء 🔧
• عروض حصرية 🎁

🔗 اضغط على الزر أدناه لفتح القناة."""
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📢 افتح القناة", url=f"https://t.me/{updates_channel}")], [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
    else:
        text = """📢 **لم يتم تعيين قناة التحديثات بعد**

📌 **لتعيين قناة التحديثات:**
1. استخدم `/admin_panel`
2. اضغط على `⚙️ قناة التحديثات`
3. أرسل معرف القناة

⚠️ تأكد من أن البوت مشرف في القناة."""
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("👑 الذهاب للوحة الأدمن", callback_data=CallbackData.ADMIN_PANEL)], [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def referral_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    referral_code = await db_get_referral_code(uid)
    if not referral_code:
        referral_code = await db_generate_referral_code(uid)
    stats = await db_get_referral_stats(uid)
    settings = await db_get_referral_settings()
    reward_days = int(settings.get("reward_days_per_referral", "3"))
    welcome_points = int(settings.get("welcome_bonus_points", "10"))
    text = get_text(uid, "referral_title").format(referral_code, BOT_USERNAME, referral_code, stats["total_referrals"], stats["available_days"], reward_days, welcome_points)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "copy_link"), callback_data=f"{CallbackData.REFERRAL_COPY_LINK_PREFIX}{referral_code}"), InlineKeyboardButton(get_text(uid, "claim_reward"), callback_data=CallbackData.REFERRAL_CLAIM_REWARD)], [InlineKeyboardButton(get_text(uid, "referral_list"), callback_data=CallbackData.REFERRAL_LIST), InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def referral_copy_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    referral_code = query.data.split(":")[-1] if query else context.user_data.get("referral_code")
    if not referral_code:
        return
    text = f"🔗 **رابط الإحالة الخاص بك:**\n`https://t.me/{BOT_USERNAME}?start=ref_{referral_code}`\n\nيمكنك الضغط مع الاستمرار على الرابط لنسخه."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.REFERRAL_MENU)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def referral_claim_reward_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    stats = await db_get_referral_stats(uid)
    if stats["available_days"] <= 0:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.REFERRAL_MENU)]])
        if query:
            await safe_edit_markdown(query, get_text(uid, "no_reward_available"), reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, get_text(uid, "no_reward_available"), reply_markup=kb)
        return
    claimed = await db_claim_referral_reward(uid)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.REFERRAL_MENU)]])
    if query:
        await safe_edit_markdown(query, get_text(uid, "reward_claimed").format(claimed), reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, get_text(uid, "reward_claimed").format(claimed), reply_markup=kb)

async def referral_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    async def _get_referrals(conn):
        cur = await conn.execute("SELECT r.referred_id, r.referred_at, r.is_rewarded, u.first_name, u.username FROM referrals r LEFT JOIN users_cache u ON r.referred_id = u.user_id WHERE r.referrer_id = ? ORDER BY r.referred_at DESC LIMIT 20", (uid,))
        return await cur.fetchall()
    referrals = await execute_db(_get_referrals)
    if not referrals:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.REFERRAL_MENU)]])
        if query:
            await safe_edit_markdown(query, get_text(uid, "no_referrals"), reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, get_text(uid, "no_referrals"), reply_markup=kb)
        return
    text = f"📊 **{get_text(uid, 'referral_list')}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for referred_id, referred_at, is_rewarded, first_name, username in referrals:
        try:
            referred_dt = datetime.fromisoformat(referred_at)
            referred_mecca = utc_to_mecca(referred_dt)
            date_str = referred_mecca.strftime("%Y-%m-%d")
        except:
            date_str = referred_at[:10] if referred_at else "تاريخ غير معروف"
        status = "✅" if is_rewarded else "⏳"
        name = first_name or username or str(referred_id)
        text += f"{status} {name} - {date_str}\n"
    text += "\n✅ = تم منح المكافأة  |  ⏳ = قيد الانتظار"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "claim_reward"), callback_data=CallbackData.REFERRAL_CLAIM_REWARD)], [InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.REFERRAL_MENU)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def reminder_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    settings = await db_get_user_reminder_settings(uid)
    status_sub = "🟢 مفعل" if settings["subscription_reminder"] else "🔴 معطل"
    status_daily = "🟢 مفعل" if settings["daily_stats_reminder"] else "🔴 معطل"
    status_weekly = "🟢 مفعل" if settings["weekly_report"] else "🔴 معطل"
    text = get_text(uid, "reminder_title").format(status_sub, status_daily, status_weekly, settings["reminder_days_before"])
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "reminder_sub"), callback_data=CallbackData.REMINDER_TOGGLE_SUB), InlineKeyboardButton(get_text(uid, "reminder_daily"), callback_data=CallbackData.REMINDER_TOGGLE_DAILY)], [InlineKeyboardButton(get_text(uid, "reminder_weekly"), callback_data=CallbackData.REMINDER_TOGGLE_WEEKLY), InlineKeyboardButton(get_text(uid, "reminder_days_btn"), callback_data=CallbackData.REMINDER_SET_DAYS)], [InlineKeyboardButton(get_text(uid, "reminder_lang_btn"), callback_data=CallbackData.REMINDER_SET_LANG), InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def reminder_toggle_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    settings = await db_get_user_reminder_settings(uid)
    await db_update_reminder_settings(uid, subscription_reminder=not settings["subscription_reminder"])
    await reminder_menu_callback(update, context)

async def reminder_toggle_daily_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    settings = await db_get_user_reminder_settings(uid)
    await db_update_reminder_settings(uid, daily_stats_reminder=not settings["daily_stats_reminder"])
    await reminder_menu_callback(update, context)

async def reminder_toggle_weekly_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    settings = await db_get_user_reminder_settings(uid)
    await db_update_reminder_settings(uid, weekly_report=not settings["weekly_report"])
    await reminder_menu_callback(update, context)

async def reminder_set_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    context.user_data["state"] = "WAITING_REMINDER_DAYS"
    msg = "⏰ **عدد أيام التذكير**\n\nأرسل عدد الأيام التي تريد أن يتم تذكيرك بها قبل انتهاء الاشتراك (1-10 أيام):"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.REMINDER_MENU)]])
    if query:
        await query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

async def reminder_set_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("العربية 🇸🇦", callback_data=f"{CallbackData.REMINDER_LANG_PREFIX}ar"), InlineKeyboardButton("English 🇬🇧", callback_data=f"{CallbackData.REMINDER_LANG_PREFIX}en")], [InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.REMINDER_MENU)]])
    msg = "🌐 **اختر لغة الإشعارات:**"
    if query:
        await query.edit_message_text(msg, reply_markup=keyboard)
    else:
        await update.message.reply_text(msg, reply_markup=keyboard)

async def reminder_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    lang = query.data.split(":")[-1] if query else context.user_data.get("reminder_lang")
    if not lang:
        return
    await db_update_reminder_settings(uid, notification_lang=lang)
    await reminder_menu_callback(update, context)

async def translation_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    current_lang = await get_user_translation_language(uid)
    if current_lang == "off":
        status_text = get_text(uid, "translation_status_off")
    elif current_lang == "ar":
        status_text = get_text(uid, "translation_status_on").format("العربية")
    elif current_lang == "en":
        status_text = get_text(uid, "translation_status_on").format("English")
    elif current_lang == "fr":
        status_text = get_text(uid, "translation_status_on").format("Français")
    elif current_lang == "tr":
        status_text = get_text(uid, "translation_status_on").format("Türkçe")
    elif current_lang == "zh":
        status_text = get_text(uid, "translation_status_on").format("中文")
    elif current_lang == "ru":
        status_text = get_text(uid, "translation_status_on").format("Русский")
    elif current_lang == "de":
        status_text = get_text(uid, "translation_status_on").format("Deutsch")
    elif current_lang == "es":
        status_text = get_text(uid, "translation_status_on").format("Español")
    elif current_lang == "it":
        status_text = get_text(uid, "translation_status_on").format("Italiano")
    elif current_lang == "pt":
        status_text = get_text(uid, "translation_status_on").format("Português")
    elif current_lang == "ja":
        status_text = get_text(uid, "translation_status_on").format("日本語")
    elif current_lang == "ko":
        status_text = get_text(uid, "translation_status_on").format("한국어")
    else:
        status_text = get_text(uid, "translation_status_off")
    text = f"""🌐 **{get_text(uid, 'translation_settings')}**
━━━━━━━━━━━━━━━━━━━━━━
📌 **الحالة:** {status_text}
{get_text(uid, 'translation_how_it_works')}
━━━━━━━━━━━━━━━━━━━━━━
{get_text(uid, 'translation_choose')}"""
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "translation_off"), callback_data=CallbackData.TRANSLATION_OFF)], [InlineKeyboardButton("🇸🇦 العربية", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}ar"), InlineKeyboardButton("🇬🇧 English", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}en")], [InlineKeyboardButton("🇫🇷 Français", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}fr"), InlineKeyboardButton("🇹🇷 Türkçe", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}tr")], [InlineKeyboardButton("🇨🇳 中文", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}zh"), InlineKeyboardButton("🇷🇺 Русский", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}ru")], [InlineKeyboardButton("🇩🇪 Deutsch", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}de"), InlineKeyboardButton("🇪🇸 Español", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}es")], [InlineKeyboardButton("🇮🇹 Italiano", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}it"), InlineKeyboardButton("🇵🇹 Português", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}pt")], [InlineKeyboardButton("🇯🇵 日本語", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}ja"), InlineKeyboardButton("🇰🇷 한국어", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}ko")], [InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def translation_off_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    await set_user_translation_language(uid, "off")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]])
    if query:
        await query.edit_message_text(get_text(uid, "translation_disabled"), reply_markup=kb)
    else:
        await update.message.reply_text(get_text(uid, "translation_disabled"), reply_markup=kb)

async def translation_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    lang = query.data.split(":")[-1] if query else context.user_data.get("translation_lang")
    if not lang:
        return
    await set_user_translation_language(uid, lang)
    lang_names = {"ar": "العربية", "en": "English", "fr": "Français", "tr": "Türkçe", "zh": "中文", "ru": "Русский", "de": "Deutsch", "es": "Español", "it": "Italiano", "pt": "Português", "ja": "日本語", "ko": "한국어"}
    lang_name = lang_names.get(lang, lang)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]])
    if query:
        await query.edit_message_text(get_text(uid, "translation_enabled").format(lang_name), reply_markup=kb)
    else:
        await update.message.reply_text(get_text(uid, "translation_enabled").format(lang_name), reply_markup=kb)

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(uid, "admin_users"), callback_data=CallbackData.ADMIN_USERS), InlineKeyboardButton(get_text(uid, "admin_banned"), callback_data=CallbackData.ADMIN_BANNED_USERS)],
        [InlineKeyboardButton(get_text(uid, "admin_channels"), callback_data=CallbackData.ADMIN_ALL_CHANNELS), InlineKeyboardButton("⛔ قنوات محظورة", callback_data=CallbackData.ADMIN_BANNED_CHANNELS)],
        [InlineKeyboardButton("📊 المجموعات", callback_data=CallbackData.ADMIN_GROUPS), InlineKeyboardButton("🚷 مجموعات محظورة", callback_data=CallbackData.ADMIN_BANNED_GROUPS)],
        [InlineKeyboardButton("📢 قنوات البوت", callback_data=CallbackData.ADMIN_BOT_CHANNELS), InlineKeyboardButton("🚫 قنوات بوت محظورة", callback_data=CallbackData.ADMIN_BANNED_BOT_CHANNELS)],
        [InlineKeyboardButton("❤️ تنشيط الكل", callback_data=CallbackData.ADMIN_ACTIVATE_ALL_CHANNELS), InlineKeyboardButton("📂 مراقبة المستخدمين", callback_data=CallbackData.ADMIN_MONITOR_USERS)],
        [InlineKeyboardButton("👑 + مشرف", callback_data=CallbackData.ADMIN_ADD_ADMIN), InlineKeyboardButton("🗑️ - مشرف", callback_data=CallbackData.ADMIN_REMOVE_ADMIN)],
        [InlineKeyboardButton("💬 ردود المجموعة", callback_data=CallbackData.ADMIN_REPLIES), InlineKeyboardButton("🚫 كلمات محظورة (عامة)", callback_data=CallbackData.ADMIN_BANNED_WORDS)],
        [InlineKeyboardButton("📝 إعدادات الردود", callback_data=CallbackData.ADMIN_AUTO_REPLY)],
        [InlineKeyboardButton("🔒 إعدادات NSFW", callback_data=CallbackData.NSFW_SETTINGS)],
        [InlineKeyboardButton("🏆 إنشاء مسابقة", callback_data=CallbackData.ADMIN_CREATE_CONTEST), InlineKeyboardButton("🏅 إعلان فائز", callback_data=CallbackData.ADMIN_DECLARE_WINNER)],
        [InlineKeyboardButton("🛠️ إجراءات متقدمة", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:0")],
        [InlineKeyboardButton("🖥️ حالة الرام", callback_data=CallbackData.ADMIN_RAM), InlineKeyboardButton("📊 إحصائيات عامة", callback_data=CallbackData.ADMIN_STATS)],
        [InlineKeyboardButton("📈 مقاييس الأداء", callback_data=CallbackData.ADMIN_METRICS)],
        [InlineKeyboardButton("💾 نسخة احتياطية", callback_data=CallbackData.ADMIN_BACKUP), InlineKeyboardButton("🔄 استعادة نسخة", callback_data=CallbackData.ADMIN_RESTORE_BACKUP)],
        [InlineKeyboardButton("⏱️ وقت النشر (عام)", callback_data=CallbackData.ADMIN_CHANGE_INTERVAL), InlineKeyboardButton("⚙️ إعدادات النسخ", callback_data=CallbackData.ADMIN_BACKUP_SETTINGS)],
        [InlineKeyboardButton("📢 نشر تحديث", callback_data=CallbackData.ADMIN_SEND_UPDATE), InlineKeyboardButton("⚙️ قناة التحديثات", callback_data=CallbackData.ADMIN_SET_UPDATE_CHANNEL)],
        [InlineKeyboardButton("📢 عرض القناة الحالية", callback_data=CallbackData.ADMIN_SHOW_UPDATE_CHANNEL)],
        [InlineKeyboardButton("🔄 التحديثات", callback_data=CallbackData.ADMIN_UPDATES), InlineKeyboardButton("🔒 الاشتراك الإجباري", callback_data=CallbackData.ADMIN_FORCE_SUBSCRIBE)],
        [InlineKeyboardButton("⚙️ تعيين القناة", callback_data=CallbackData.ADMIN_SET_FORCE_CHANNEL), InlineKeyboardButton("📨 إرسال رسالة", callback_data=CallbackData.ADMIN_BROADCAST)],
        [InlineKeyboardButton("📋 تذاكر الدعم", callback_data=CallbackData.ADMIN_SUPPORT_TICKETS), InlineKeyboardButton("🗑️ حذف جميع التذاكر", callback_data=CallbackData.ADMIN_DELETE_ALL_TICKETS)],
        [InlineKeyboardButton("📁 صلاحية /sendcode", callback_data=CallbackData.ADMIN_MANAGE_SENDCODE), InlineKeyboardButton("📋 قناة التقارير", callback_data=CallbackData.ADMIN_SHOW_LOG_CHANNEL)],
        [InlineKeyboardButton("📋 تعيين قناة التقارير", callback_data=CallbackData.ADMIN_SET_LOG_CHANNEL)],
        [InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, get_text(uid, "admin_panel"), reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, get_text(uid, "admin_panel"), reply_markup=kb)

async def admin_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    users = await db_get_all_users()
    if not users:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا يوجد مستخدمون مسجلون.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا يوجد مستخدمون مسجلون.", reply_markup=kb)
        return
    text = "👥 **قائمة المستخدمين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for user_id, banned in users[:50]:
        status = "🚫 محظور" if banned else "✅ نشط"
        text += f"• `{user_id}` - {status}\n"
    if len(users) > 50:
        text += f"\nو {len(users)-50} آخرون..."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_banned_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    users = await db_get_all_users()
    banned_users = [u for u in users if u[1] == 1]
    if not banned_users:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا يوجد مستخدمون محظورون.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا يوجد مستخدمون محظورون.", reply_markup=kb)
        return
    text = "🚫 **المستخدمون المحظورون**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for user_id, _ in banned_users[:50]:
        text += f"• `{user_id}`\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_USERS)], [InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def admin_unban_all_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    async def _unban_all(conn):
        await conn.execute("UPDATE users SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_unban_all)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text("✅ تم إلغاء حظر جميع المستخدمين.", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم إلغاء حظر جميع المستخدمين.", reply_markup=kb)

async def admin_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    channels = await db_get_all_user_channels_no_limit()
    if not channels:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد قنوات مسجلة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد قنوات مسجلة.", reply_markup=kb)
        return
    text = "📡 **قنوات المستخدمين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    for idx, (user_id, ch_id, ch_tele, ch_name, banned) in enumerate(channels[:100], 1):
        status = "⛔ محظورة" if banned else "✅ نشطة"
        ban_status_text = "🔓 إلغاء الحظر" if banned else "⛔ حظر"
        ban_callback = f"{CallbackData.ADMIN_TOGGLE_CHANNEL_BAN_PREFIX}{ch_id}"
        text += f"{idx}. {status} `{ch_name}`\n   👤 المستخدم: `{user_id}`\n   🆔 القناة: `{ch_tele}`\n"
        keyboard.append([InlineKeyboardButton(ban_status_text, callback_data=ban_callback)])
    if len(channels) > 100:
        text += f"\nو {len(channels)-100} قناة أخرى..."
    keyboard.append([InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)])
    if query:
        await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_banned_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    channels = await db_all_users_channels(only_banned=True, limit=500)
    if not channels:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد قنوات محظورة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد قنوات محظورة.", reply_markup=kb)
        return
    text = "⛔ **قنوات المستخدمين المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for user_id, ch_id, ch_tele, ch_name, banned in channels[:50]:
        text += f"• المستخدم: `{user_id}` | القناة: {ch_name} (`{ch_tele}`)\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❤️ تنشيط الكل", callback_data=CallbackData.ADMIN_ACTIVATE_ALL_CHANNELS)], [InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def admin_activate_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    async def _activate_all(conn):
        await conn.execute("UPDATE user_channels SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_activate_all)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text("✅ تم إلغاء حظر جميع قنوات المستخدمين.", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم إلغاء حظر جميع قنوات المستخدمين.", reply_markup=kb)

async def admin_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    groups = await db_get_all_groups(only_banned=False)
    if not groups:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد مجموعات مسجلة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد مجموعات مسجلة.", reply_markup=kb)
        return
    text = "👥 **المجموعات المسجلة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    for chat_id, chat_name, username, added_by, added_at, banned in groups[:50]:
        status = "⛔ محظورة" if banned else "✅ نشطة"
        ban_status_text = "🔓 إلغاء الحظر" if banned else "⛔ حظر"
        ban_callback = f"{CallbackData.ADMIN_TOGGLE_GROUP_BAN_PREFIX}{chat_id}"
        text += f"• {chat_name} (ID: `{chat_id}`)\n  أضيف بواسطة: `{added_by}`\n  الحالة: {status}\n"
        keyboard.append([InlineKeyboardButton(ban_status_text, callback_data=ban_callback)])
    if len(groups) > 50:
        text += f"\nو {len(groups)-50} أخرى..."
    keyboard.append([InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)])
    if query:
        await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_banned_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    groups = await db_get_all_groups(only_banned=True)
    if not groups:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد مجموعات محظورة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد مجموعات محظورة.", reply_markup=kb)
        return
    text = "🚷 **المجموعات المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for chat_id, chat_name, username, added_by, added_at, banned in groups[:50]:
        text += f"• {chat_name} (ID: `{chat_id}`)\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_GROUPS)], [InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def admin_unban_all_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    async def _unban_groups(conn):
        await conn.execute("UPDATE bot_groups SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_unban_groups)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text("✅ تم إلغاء حظر جميع المجموعات.", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم إلغاء حظر جميع المجموعات.", reply_markup=kb)

async def admin_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    channels = await db_get_all_bot_channels(only_banned=False)
    if not channels:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد قنوات أضيف إليها البوت.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد قنوات أضيف إليها البوت.", reply_markup=kb)
        return
    text = "📢 **قنوات البوت**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for channel_id, channel_name, added_by, added_at, banned in channels[:50]:
        text += f"• {channel_name} (ID: `{channel_id}`)\n  أضيف بواسطة: `{added_by}`\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_banned_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    channels = await db_get_all_bot_channels(only_banned=True)
    if not channels:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد قنوات بوت محظورة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد قنوات بوت محظورة.", reply_markup=kb)
        return
    text = "🚫 **قنوات البوت المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for channel_id, channel_name, added_by, added_at, banned in channels[:50]:
        text += f"• {channel_name} (ID: `{channel_id}`)\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_BOT_CHANNELS)], [InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def admin_unban_all_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    async def _unban_bot_channels(conn):
        await conn.execute("UPDATE bot_channels SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_unban_bot_channels)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text("✅ تم إلغاء حظر جميع قنوات البوت.", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم إلغاء حظر جميع قنوات البوت.", reply_markup=kb)

async def admin_monitor_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    all_users = await db_get_all_users()
    total_users = len(all_users)
    active_users = len([u for u in all_users if u[1] == 0])
    banned_users = len([u for u in all_users if u[1] == 1])
    admins_list = await get_all_bot_admins()
    admin_count = len(admins_list)
    all_channels = await db_all_users_channels()
    channels_count = len(all_channels)
    all_groups = await db_get_all_groups()
    groups_count = len(all_groups)
    text = f"📂 **مراقبة المستخدمين**\n━━━━━━━━━━━━━━━━━━━━━━\n👥 **إجمالي المستخدمين:** `{total_users}`\n✅ **النشطاء:** `{active_users}`\n🚫 **المحظورون:** `{banned_users}`\n👑 **المشرفون:** `{admin_count}`\n━━━━━━━━━━━━━━━━━━━━━━\n📡 **قنوات المستخدمين:** `{channels_count}`\n👥 **المجموعات المسجلة:** `{groups_count}`\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_add_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    context.user_data["state"] = "WAITING_ADMIN_ID_ADD"
    if query:
        await safe_edit_markdown(query, get_text(uid, "enter_admin_id"))
    else:
        await update.message.reply_text(get_text(uid, "enter_admin_id"))

async def admin_remove_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    admins = await get_all_bot_admins()
    if not admins:
        if query:
            await query.edit_message_text(get_text(uid, "no_admins"))
        else:
            await update.message.reply_text(get_text(uid, "no_admins"))
        return
    text = "👑 المشرفون الحاليون:\n"
    for a in admins:
        text += f"- {a}\n"
    text += "\n" + get_text(uid, "enter_remove_admin_id")
    context.user_data["state"] = "WAITING_ADMIN_ID_REMOVE"
    if query:
        await safe_edit_markdown(query, text)
    else:
        await update.message.reply_text(text)

async def admin_ram_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    ram = get_ram_usage()
    text = f"🖥️ **حالة الرام**\n━━━━━━━━━━━━━━━━━━━━━━\n• الإجمالي: {ram['total']} GB\n• المستخدم: {ram['used']} GB\n• النسبة: {ram['percent']}%"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    total, banned, posts, groups, channels = await db_stats()
    text = f"📊 **إحصائيات عامة**\n━━━━━━━━━━━━━━━━━━━━━━\n• المستخدمين: {total}\n• المحظورين: {banned}\n• المنشورات غير المنشورة: {posts}\n• المجموعات: {groups}\n• قنوات المستخدمين: {channels}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_metrics_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    text = "📈 **مقاييس الأداء**\n━━━━━━━━━━━━━━━━━━━━━━\n⏱️ **وقت التشغيل:** قيد التطوير\n📊 **إجمالي الأوامر:** قيد التطوير\n⚡ **متوسط وقت الاستجابة:** قيد التطوير"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    try:
        backup_file = await create_backup()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
        msg = f"✅ تم إنشاء نسخة احتياطية مشفرة جديدة.\n\n📁 اسم الملف: `{backup_file.name}`\n📂 الموقع: `{backup_file.parent}`"
        if query:
            await safe_edit_markdown(query, msg, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, msg, reply_markup=kb)
    except Exception as e:
        error_id = log_error(e, {"user_id": uid, "action": "admin_backup"})
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
        msg = f"❌ فشل إنشاء النسخة (الرمز: `{error_id}`)"
        if query:
            await safe_edit_markdown(query, msg, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, msg, reply_markup=kb)

async def admin_restore_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    backups = await list_backups()
    if not backups:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text(get_text(uid, "no_backups"), reply_markup=kb)
        else:
            await update.message.reply_text(get_text(uid, "no_backups"), reply_markup=kb)
        return
    kb = []
    for b in backups[:10]:
        kb.append([InlineKeyboardButton(b.name, callback_data=f"{CallbackData.ADMIN_RESTORE_BACKUP_SELECT_PREFIX}{b.name}")])
    kb.append([InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)])
    if query:
        await query.edit_message_text(get_text(uid, "select_backup"), reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(get_text(uid, "select_backup"), reply_markup=InlineKeyboardMarkup(kb))

async def admin_restore_backup_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    backup_name = query.data.split(":")[-1] if query else context.user_data.get("restore_backup_name")
    if not backup_name:
        return
    backup_path = BACKUP_DIR / backup_name
    try:
        with open(backup_path, "rb") as f:
            encrypted = f.read()
        BACKUP_CIPHER.decrypt(encrypted)
        await restore_backup(backup_path)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
        msg = f"✅ تم استعادة النسخة الاحتياطية المشفرة بنجاح.\n\n📁 الملف: `{backup_name}`"
        if query:
            await safe_edit_markdown(query, msg, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, msg, reply_markup=kb)
    except Exception as e:
        error_id = log_error(e, {"user_id": uid, "backup": backup_name})
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
        msg = f"❌ فشل استعادة النسخة (الرمز: `{error_id}`)\nقد تكون النسخة تالفة أو غير صالحة."
        if query:
            await safe_edit_markdown(query, msg, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, msg, reply_markup=kb)

async def admin_backup_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    auto = await db_get_auto_backup()
    status = "مفعل" if auto else "معطل"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 تبديل النسخ التلقائي", callback_data=CallbackData.ADMIN_TOGGLE_AUTO_BACKUP)], [InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    text = f"⚙️ **إعدادات النسخ الاحتياطي**\n━━━━━━━━━━━━━━━━━━━━━━\n• النسخ التلقائي: {status}\n• تشفير النسخ: ✅ مفعل\n• الحد الأقصى للنسخ: {MAX_BACKUPS}\n• دعم Google Drive: {'✅ مفعل' if CLOUD_BACKUP_ENABLED else '❌ معطل'}\n\nيمكنك تبديل الحالة بالزر أدناه."
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_toggle_auto_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    auto = await db_get_auto_backup()
    new_auto = not auto
    await db_set_auto_backup(new_auto)
    status = "مفعل" if new_auto else "معطل"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_BACKUP_SETTINGS)]])
    if query:
        await query.edit_message_text(f"✅ تم تغيير إعداد النسخ التلقائي إلى: {status}", reply_markup=kb)
    else:
        await update.message.reply_text(f"✅ تم تغيير إعداد النسخ التلقائي إلى: {status}", reply_markup=kb)

async def admin_change_interval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    current = await db_get_publish_interval()
    current_min = current // 60
    context.user_data["state"] = "WAITING_INTERVAL_MINUTES"
    context.user_data["admin_interval"] = True
    msg = f"⏱️ **وقت النشر العام الحالي:** {current_min} دقيقة\n\n📌 **ملاحظة:** هذا الإعداد يؤثر على الفاصل الزمني بين دورات النشر.\nأرسل العدد الجديد من الدقائق (الحد الأدنى 1 دقيقة، الحد الأقصى 1440 دقيقة = 24 ساعة):"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def admin_send_update_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    channel = await db_get_updates_channel()
    if not channel:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ تعيين قناة", callback_data=CallbackData.ADMIN_SET_UPDATE_CHANNEL)], [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
        msg = "⚠️ **لم يتم تعيين قناة تحديثات بعد!**\n\nيرجى تعيين قناة التحديثات أولاً باستخدام الزر أدناه."
        if query:
            await safe_edit_markdown(query, msg, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, msg, reply_markup=kb)
        return
    context.user_data["state"] = "WAITING_UPDATE_TEXT"
    msg = f"📢 أرسل نص التحديث الذي تريد نشره في قناة التحديثات @{channel}:"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def admin_set_update_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    context.user_data["state"] = "WAITING_UPDATE_CHANNEL"
    msg = """⚙️ **تعيين قناة التحديثات**

📢 أرسل معرف قناة التحديثات:

• `@username` (مثل: @my_channel)
• أو المعرف الرقمي (مثل: -1001234567890)

⚠️ **تنبيهات مهمة:**
• تأكد من أن البوت مشرف في القناة
• تأكد من أن البوت لديه صلاحية الإرسال
• القناة يجب أن تكون عامة (Public)"""
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def admin_show_update_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    channel = await db_get_updates_channel()
    if channel:
        text = f"📢 **قناة التحديثات الحالية:**\n`@{channel}`"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📢 فتح القناة", url=f"https://t.me/{channel}")], [InlineKeyboardButton("🔄 تغيير القناة", callback_data=CallbackData.ADMIN_SET_UPDATE_CHANNEL)], [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    else:
        text = "📢 **لم يتم تعيين قناة تحديثات بعد**"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("➕ تعيين قناة", callback_data=CallbackData.ADMIN_SET_UPDATE_CHANNEL)], [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_updates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    channel = await db_get_updates_channel()
    text = f"📢 **قناة التحديثات الحالية:** @{channel}\n\nيمكنك تغييرها باستخدام زر '⚙️ قناة التحديثات'"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_force_subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    enabled = await db_get_force_subscribe_status()
    new_status = not enabled
    await db_set_force_subscribe_status(new_status)
    status_text = "مفعل" if new_status else "معطل"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text(f"✅ تم {status_text} الاشتراك الإجباري.", reply_markup=kb)
    else:
        await update.message.reply_text(f"✅ تم {status_text} الاشتراك الإجباري.", reply_markup=kb)

async def admin_set_force_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    context.user_data["state"] = "WAITING_FORCE_CHANNEL"
    msg = "⚙️ أرسل معرف قناة الاشتراك الإجباري (مثال: @channel_username):"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def admin_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    context.user_data["state"] = "WAITING_BROADCAST"
    msg = "📨 أرسل النص الذي تريد إرساله إلى جميع المستخدمين:"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def admin_confirm_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    broadcast_text = context.user_data.get("broadcast_text", "")
    if not broadcast_text:
        if query:
            await query.edit_message_text("❌ لا يوجد نص للإرسال")
        else:
            await update.message.reply_text("❌ لا يوجد نص للإرسال")
        return
    dangerous_patterns = [r"<script", r"javascript:", r"data:", r"vbscript:", r"<\?php", r"<%", r"{%"]
    for pattern in dangerous_patterns:
        if re.search(pattern, broadcast_text, re.IGNORECASE):
            if query:
                await query.edit_message_text("❌ النص يحتوي على كود ضار! تم منع الإرسال.")
            else:
                await update.message.reply_text("❌ النص يحتوي على كود ضار! تم منع الإرسال.")
            return
    if len(broadcast_text) > 4000:
        if query:
            await query.edit_message_text("❌ النص طويل جداً (الحد الأقصى 4000 حرف)")
        else:
            await update.message.reply_text("❌ النص طويل جداً (الحد الأقصى 4000 حرف)")
        return
    if query:
        await query.edit_message_text("📨 جاري الإرسال... يرجى الانتظار")
    else:
        await update.message.reply_text("📨 جاري الإرسال... يرجى الانتظار")
    async def _get_active_users(conn):
        cur = await conn.execute("SELECT user_id FROM users WHERE banned = 0")
        return [row[0] for row in await cur.fetchall()]
    users = await execute_db(_get_active_users)
    sent = 0
    failed = 0
    if not users:
        if query:
            await query.edit_message_text("📭 لا يوجد مستخدمين نشطين لإرسال الرسالة لهم.")
        else:
            await update.message.reply_text("📭 لا يوجد مستخدمين نشطين لإرسال الرسالة لهم.")
        return
    sem = asyncio.Semaphore(20)
    async def send_one(user_id):
        async with sem:
            try:
                await safe_send_markdown(context.bot, user_id, broadcast_text)
                return True
            except:
                return False
    tasks = [send_one(uid) for uid in users]
    results = await asyncio.gather(*tasks)
    sent = sum(results)
    failed = len(results) - sent
    context.user_data.pop("broadcast_text", None)
    context.user_data.pop("state", None)
    msg = f"✅ **تم إرسال الرسالة**\n\n📨 تم الإرسال إلى: {sent} مستخدم\n❌ فشل الإرسال إلى: {failed} مستخدم"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

async def admin_support_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    tickets = await db_get_all_tickets(limit=20)
    if not tickets:
        if query:
            await query.edit_message_text("📭 لا توجد تذاكر دعم مسجلة")
        else:
            await update.message.reply_text("📭 لا توجد تذاكر دعم مسجلة")
        return
    text = "📋 **تذاكر الدعم**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for tid, uid_u, username, msg, ticket_num, status, created_at in tickets:
        try:
            created_utc = datetime.fromisoformat(created_at)
            created_mecca = utc_to_mecca(created_utc)
            created_str = created_mecca.strftime("%Y-%m-%d %H:%M")
        except:
            created_str = created_at
        status_icon = "🟡" if status == "pending" else "🟢"
        msg_preview = msg[:40] + "..." if len(msg) > 40 else msg
        text += f"\n{status_icon} #{ticket_num} | 👤 {username}\n🆔 `{uid_u}` | 📅 {created_str}\n📝 {msg_preview}\n💡 `/support_reply {uid_u} نص الرد`\n━━━━━━━━━━━━━━━━━━━━━━\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_delete_all_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    confirm_kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ نعم، احذف الكل", callback_data=CallbackData.ADMIN_CONFIRM_DELETE_TICKETS), InlineKeyboardButton("❌ لا، إلغاء", callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text(get_text(uid, "confirm_delete_tickets"), reply_markup=confirm_kb)
    else:
        await update.message.reply_text(get_text(uid, "confirm_delete_tickets"), reply_markup=confirm_kb)

async def admin_confirm_delete_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    count = await db_delete_all_tickets()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text(get_text(uid, "tickets_deleted").format(count), reply_markup=kb)
    else:
        await update.message.reply_text(get_text(uid, "tickets_deleted").format(count), reply_markup=kb)

async def admin_manage_sendcode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    allowed_user = await db_get_allowed_sendcode_user()
    if allowed_user:
        current_text = get_text(uid, "current_allowed_user").format(f"`{allowed_user}`")
    else:
        current_text = get_text(uid, "current_allowed_user").format(get_text(uid, "no_allowed_user"))
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "set_new_sendcode_user"), callback_data=CallbackData.ADMIN_SET_SENDCODE_USER)], [InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, current_text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, current_text, reply_markup=keyboard)

async def admin_set_sendcode_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    context.user_data["state"] = "WAITING_SENDCODE_USER"
    msg = "➕ أرسل معرف المستخدم (user_id) الذي تريد منحه صلاحية استخدام أمر /sendcode:"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def admin_show_log_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    log_ch = await db_get_log_channel_id()
    if log_ch:
        text = f"📋 **قناة التقارير الحالية:**\n`{log_ch}`\n\nيمكنك تغييرها باستخدام الأمر `/set_log_channel`\nأو الضغط على زر 'تعيين قناة التقارير'."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await safe_edit_markdown(query, text, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=kb)
    else:
        text = "📋 **لم يتم تعيين قناة تقارير بعد.**\nاستخدم الأمر `/set_log_channel` أو زر 'تعيين قناة التقارير' لتعيينها."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text(text, reply_markup=kb)
        else:
            await update.message.reply_text(text, reply_markup=kb)

async def admin_set_log_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    context.user_data["state"] = "WAITING_LOG_CHANNEL"
    msg = "📢 **تعيين قناة التقارير**\n\nأرسل معرف القناة (ID) أو معرف المستخدم (@username) للقناة التي تريد استقبال التقارير فيها.\n\nمثال: `-1001234567890` أو `@channel_username`\n\n⚠️ تأكد من أن البوت مشرف في القناة ولديه صلاحية إرسال الرسائل."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

async def admin_replies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    msg = "💬 **إدارة ردود المجموعة**"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ إضافة رد", callback_data=CallbackData.ADMIN_ADD_REPLY), InlineKeyboardButton("📋 عرض الردود", callback_data=CallbackData.ADMIN_LIST_REPLIES)], [InlineKeyboardButton("🗑️ حذف رد", callback_data=CallbackData.ADMIN_DEL_REPLY), InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

async def admin_add_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    context.user_data["state"] = "WAITING_KEYWORD"
    msg = "📝 **إضافة رد تلقائي**\n\nأرسل الكلمة المفتاحية (مثل: مرحبا، السلام عليكم، كيف حالك):"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def admin_list_replies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    replies = await db_get_all_replies()
    if not replies:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_REPLIES)]])
        if query:
            await query.edit_message_text("📭 لا توجد ردود مسجلة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد ردود مسجلة.", reply_markup=kb)
        return
    text = "💬 **قائمة الردود التلقائية**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    for kw, rep in replies[:30]:
        short_rep = rep[:40] + "..." if len(rep) > 40 else rep
        text += f"• **{kw}** → {short_rep}\n"
        keyboard.append([InlineKeyboardButton(f"🗑️ حذف {kw}", callback_data=f"admin_del_reply_{kw}")])
    keyboard.append([InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_REPLIES)])
    if query:
        await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_del_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    if query and query.data.startswith("admin_del_reply_"):
        keyword = query.data.replace("admin_del_reply_", "")
        if await db_del_reply(keyword):
            await query.answer(f"✅ تم حذف رد {keyword}", show_alert=True)
        else:
            await query.answer(f"❌ الكلمة {keyword} غير موجودة", show_alert=True)
        await admin_list_replies_callback(update, context)
        return
    else:
        context.user_data["state"] = "WAITING_REPLY"
        context.user_data["admin_del_reply"] = True
        msg = "🗑️ **حذف رد تلقائي**\n\nأرسل الكلمة المفتاحية لحذف ردها:"
        if query:
            await query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)

async def admin_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    msg = "🚫 **إدارة الكلمات المحظورة على مستوى البوت (لجميع المجموعات)**"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ إضافة كلمة عامة", callback_data=CallbackData.ADMIN_ADD_BANNED_WORD), InlineKeyboardButton("📋 عرض الكلمات", callback_data=CallbackData.ADMIN_LIST_BANNED_WORDS)], [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=CallbackData.ADMIN_REMOVE_BANNED_WORD), InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

async def admin_add_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    context.user_data["state"] = "WAITING_GLOBAL_BANNED_WORD"
    msg = "➕ أرسل الكلمة التي تريد حظرها على مستوى البوت:"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def admin_list_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    words = await db_get_banned_words(-1)
    if not words:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_BANNED_WORDS)]])
        if query:
            await query.edit_message_text("📭 لا توجد كلمات محظورة عامة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد كلمات محظورة عامة.", reply_markup=kb)
        return
    text = "🚫 **الكلمات المحظورة عامة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    for w, by, at in words[:20]:
        text += f"• `{w}` (أضيف بواسطة {by})\n"
        keyboard.append([InlineKeyboardButton(f"🗑️ حذف {w}", callback_data=f"admin_del_banned_word_{w}")])
    keyboard.append([InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.ADMIN_BANNED_WORDS)])
    if query:
        await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_remove_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    context.user_data["state"] = "WAITING_REMOVE_GLOBAL_BANNED_WORD"
    msg = "🗑️ أرسل الكلمة التي تريد حذفها من الكلمات المحظورة العامة:"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def admin_del_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    word = query.data.replace("admin_del_banned_word_", "") if query else context.user_data.get("del_banned_word")
    if not word:
        return
    async def _remove_global_word(conn):
        await conn.execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", (word, -1))
        await conn.commit()
    await execute_db(_remove_global_word)
    if query:
        await query.answer(f"✅ تم حذف {word}", show_alert=True)
    else:
        await update.message.reply_text(f"✅ تم حذف {word}")
    await admin_list_banned_words_callback(update, context)

async def admin_toggle_channel_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    channel_db_id = int(query.data.split(":")[-1])
    async def _get_ban(conn):
        cur = await conn.execute("SELECT banned FROM user_channels WHERE id=?", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    current = await execute_db(_get_ban)
    new_status = 0 if current == 1 else 1
    async def _update_ban(conn):
        await conn.execute("UPDATE user_channels SET banned=? WHERE id=?", (new_status, channel_db_id))
        await conn.commit()
    await execute_db(_update_ban)
    status_text = "محظورة" if new_status == 1 else "نشطة"
    if query:
        await query.answer(f"✅ تم تغيير حالة القناة إلى: {status_text}", show_alert=True)
    await admin_all_channels_callback(update, context)

async def admin_toggle_group_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    group_chat_id = int(query.data.split(":")[-1])
    async def _get_ban(conn):
        cur = await conn.execute("SELECT banned FROM bot_groups WHERE chat_id=?", (group_chat_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    current = await execute_db(_get_ban)
    new_status = 0 if current == 1 else 1
    async def _update_ban(conn):
        await conn.execute("UPDATE bot_groups SET banned=? WHERE chat_id=?", (new_status, group_chat_id))
        await conn.commit()
    await execute_db(_update_ban)
    status_text = "محظورة" if new_status == 1 else "نشطة"
    if query:
        await query.answer(f"✅ تم تغيير حالة المجموعة إلى: {status_text}", show_alert=True)
    await admin_groups_callback(update, context)

async def auto_reply_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split(":")[-1])
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    new_status = await db_toggle_auto_reply(chat_id)
    settings = await db_get_auto_reply_settings(chat_id)
    status_text = "🟢 مفعل" if new_status else "🔴 معطل"
    await query.edit_message_text(f"✅ تم تغيير حالة الردود التلقائية إلى: {status_text}", reply_markup=get_auto_reply_keyboard(chat_id, settings))

def get_auto_reply_keyboard(chat_id: int, settings: dict) -> InlineKeyboardMarkup:
    status_text = "🟢 مفعل" if settings["enabled"] else "🔴 معطل"
    admin_text = "👑 مشرفين فقط" if settings["only_admins"] else "👥 الجميع"
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"📝 الردود التلقائية: {status_text}", callback_data=f"{CallbackData.AUTO_REPLY_TOGGLE_PREFIX}{chat_id}")], [InlineKeyboardButton(f"👥 المستخدمون: {admin_text}", callback_data=f"{CallbackData.AUTO_REPLY_ADMINS_PREFIX}{chat_id}")], [InlineKeyboardButton("🔄 إعادة تعيين الردود", callback_data=f"{CallbackData.AUTO_REPLY_RESET_PREFIX}{chat_id}")], [InlineKeyboardButton("📊 إحصائيات الردود", callback_data=f"{CallbackData.AUTO_REPLY_STATS_PREFIX}{chat_id}")], [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])

async def auto_reply_admins_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split(":")[-1])
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    settings = await db_get_auto_reply_settings(chat_id)
    new_status = not settings["only_admins"]
    await db_set_auto_reply_only_admins(chat_id, new_status)
    settings = await db_get_auto_reply_settings(chat_id)
    admin_text = "👑 مشرفين فقط" if new_status else "👥 الجميع"
    await query.edit_message_text(f"✅ تم تغيير وضع الردود إلى: {admin_text}", reply_markup=get_auto_reply_keyboard(chat_id, settings))

async def auto_reply_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split(":")[-1])
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ نعم، إعادة تعيين", callback_data=f"auto_reply_confirm_reset:{chat_id}")], [InlineKeyboardButton("❌ إلغاء", callback_data=f"auto_reply_cancel:{chat_id}")]])
    await query.edit_message_text("⚠️ **تأكيد إعادة التعيين**\n\nسيتم حذف جميع الردود المخصصة في هذه المجموعة وإعادة تعيين الإعدادات إلى الافتراضية.\nالردود المدمجة (200 رد) ستبقى كما هي.\n\nهل أنت متأكد؟", reply_markup=keyboard)

async def auto_reply_confirm_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split(":")[-1])
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    async def _reset_replies(conn):
        await conn.execute("DELETE FROM group_replies WHERE keyword LIKE ?", (f"{chat_id}:%",))
        await conn.commit()
    await execute_db(_reset_replies)
    await db_set_auto_reply_enabled(chat_id, True)
    await db_set_auto_reply_only_admins(chat_id, False)
    settings = await db_get_auto_reply_settings(chat_id)
    await query.edit_message_text("✅ **تم إعادة تعيين الردود بنجاح!**\n\n• تم حذف جميع الردود المخصصة\n• تم تفعيل الردود التلقائية\n• وضع الردود: الجميع\n• 200 رد مدمج ما زالت تعمل", reply_markup=get_auto_reply_keyboard(chat_id, settings))

async def auto_reply_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split(":")[-1])
    settings = await db_get_auto_reply_settings(chat_id)
    await query.edit_message_text("❌ تم إلغاء إعادة التعيين", reply_markup=get_auto_reply_keyboard(chat_id, settings))

async def auto_reply_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split(":")[-1])
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    async def _get_stats(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM group_replies WHERE keyword LIKE ?", (f"{chat_id}:%",))
        custom_count = (await cur.fetchone())[0]
        return {"custom_replies": custom_count, "embedded_replies": len(ALL_REPLIES), "total_replies": custom_count + len(ALL_REPLIES)}
    stats = await execute_db(_get_stats)
    settings = await db_get_auto_reply_settings(chat_id)
    status_text = "🟢 مفعل" if settings["enabled"] else "🔴 معطل"
    admin_text = "👑 مشرفين فقط" if settings["only_admins"] else "👥 الجميع"
    text = f"""📊 **إحصائيات الردود التلقائية**

━━━━━━━━━━━━━━━━━━━━━━
📝 **الحالة:** {status_text}
👥 **المستخدمون:** {admin_text}
━━━━━━━━━━━━━━━━━━━━━━
📋 **الردود المخصصة:** {stats['custom_replies']}
💾 **الردود المدمجة:** {stats['embedded_replies']}
📚 **إجمالي الردود:** {stats['total_replies']}
━━━━━━━━━━━━━━━━━━━━━━

📌 **ملاحظة:** الردود المدمجة (200 رد) لا يمكن حذفها، ولكن يمكن تعطيلها."""
    await query.edit_message_text(text, reply_markup=get_auto_reply_keyboard(chat_id, settings))

async def user_auto_reply_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split(":")[-1])
    current_status = await db_get_user_auto_reply_status(user_id)
    new_status = not current_status
    await db_set_user_auto_reply_status(user_id, new_status)
    status_text = "🟢 مفعل" if new_status else "🔴 معطل"
    await query.edit_message_text(f"✅ تم تغيير حالة الردود التلقائية إلى: {status_text}", reply_markup=get_user_auto_reply_keyboard(user_id, new_status))

def get_user_auto_reply_keyboard(user_id: int, enabled: bool) -> InlineKeyboardMarkup:
    status_text = "🟢 مفعل" if enabled else "🔴 معطل"
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"📝 الردود التلقائية: {status_text}", callback_data=f"{CallbackData.USER_AUTO_REPLY_TOGGLE_PREFIX}{user_id}")], [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])

async def admin_auto_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    groups = await db_get_user_groups(user_id)
    if not groups:
        await query.edit_message_text("📭 لا توجد مجموعات مسجلة.\nأضف البوت إلى مجموعة واجعلها نشطة.")
        return
    keyboard = []
    for chat_id, chat_name, username, banned in groups:
        settings = await db_get_auto_reply_settings(chat_id)
        status = "🟢" if settings["enabled"] else "🔴"
        keyboard.append([InlineKeyboardButton(f"{status} {chat_name[:30]}", callback_data=f"admin_auto_reply_select:{chat_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)])
    await query.edit_message_text("📝 **إدارة الردود التلقائية**\n\nاختر مجموعة للتحكم في إعدادات الردود:\n🟢 = مفعل  |  🔴 = معطل", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_auto_reply_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split(":")[-1])
    settings = await db_get_auto_reply_settings(chat_id)
    async def _get_name(conn):
        cur = await conn.execute("SELECT chat_name FROM bot_groups WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        return row[0] if row else str(chat_id)
    group_name = await execute_db(_get_name)
    await query.edit_message_text(f"📝 **إعدادات الردود: {group_name}**\n\nاختر الإعداد المطلوب:", reply_markup=get_auto_reply_keyboard(chat_id, settings))

async def nsfw_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    status = "🟢 مفعل" if NSFW_ENABLED else "🔴 معطل"
    threshold = f"{NSFW_THRESHOLD * 100:.0f}%"
    text = f"""🔞 **إعدادات كشف المحتوى غير اللائق (NSFW)**

━━━━━━━━━━━━━━━━━━━━━━
📌 **الحالة:** {status}
📊 **نسبة الحساسية:** {threshold}
🖼️ **حجم الصورة الأقصى:** {NSFW_MAX_FILE_SIZE // (1024*1024)} ميجابايت
🎬 **حجم الفيديو الأقصى:** {NSFW_MAX_VIDEO_SIZE // (1024*1024)} ميجابايت
📸 **عدد إطارات الفيديو:** {NSFW_FRAMES}
🗄️ **تخزين مؤقت:** {len(NSFW_CACHE)} نتيجة
━━━━━━━━━━━━━━━━━━━━━━

📌 **الشرح:**
• عندما يرسل مستخدم صورة أو فيديو، يتحقق البوت من المحتوى
• إذا تجاوزت نسبة المحتوى غير اللائق {threshold}، يتم حذف الملف
• يتم تحليل {NSFW_FRAMES} إطارات من الفيديو للحصول على دقة أعلى
• النتائج يتم تخزينها مؤقتاً لمدة {NSFW_CACHE_TTL} ثانية

🔑 **مطلوب مفاتيح Sightengine API:**
• `SIGHTENGINE_API_USER` في ملف .env
• `SIGHTENGINE_API_SECRET` في ملف .env
• سجل مجاناً على: https://sightengine.com

⚙️ **اختر الإجراء المناسب:"""
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"{'🔴 تعطيل' if NSFW_ENABLED else '🟢 تفعيل'}", callback_data=CallbackData.NSFW_TOGGLE)], [InlineKeyboardButton("📊 تغيير نسبة الحساسية", callback_data=CallbackData.NSFW_THRESHOLD_SET)], [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def nsfw_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    global NSFW_ENABLED
    NSFW_ENABLED = not NSFW_ENABLED
    os.environ["NSFW_ENABLED"] = "True" if NSFW_ENABLED else "False"
    await nsfw_settings_callback(update, context)

async def nsfw_threshold_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    context.user_data["state"] = "WAITING_NSFW_THRESHOLD"
    msg = """📊 **تغيير نسبة حساسية كشف NSFW**

أرسل النسبة المئوية المطلوبة (من 0 إلى 100):
• 70% = حساسية متوسطة (افتراضي)
• 50% = حساسية عالية (يكتشف محتوى أقل وضوحاً)
• 90% = حساسية منخفضة (يكتشف محتوى واضحاً فقط)

مثال: أرسل `75` أو `80`

⚠️ **تنبيه:** النسبة الأقل تزيد من احتمالية الحظر الخاطئ."""
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def contests_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update or not update.effective_user:
            logger.error("update or effective_user not found")
            return
        user_id = update.effective_user.id
        contests = []
        try:
            contests = await db_get_active_contests_with_participants(limit=10)
        except Exception as e:
            logger.error(f"Error fetching contests: {e}")
            contests = []
        if not contests:
            text = get_text(user_id, "no_contests")
            if update.callback_query:
                try:
                    await safe_edit_markdown(update.callback_query, text)
                except:
                    await update.callback_query.edit_message_text(text)
            else:
                await safe_send_markdown(context.bot, user_id, text)
            return
        text = get_text(user_id, "contests_active").format("")
        keyboard = []
        for contest in contests:
            try:
                if len(contest) < 6:
                    continue
                cid = contest[0]
                title = contest[1] or "بدون عنوان"
                desc = contest[2] or ""
                prize = contest[3] or "غير محددة"
                end_date = contest[4]
                participants = contest[5] if len(contest) > 5 else 0
                contest_type = contest[6] if len(contest) > 6 else "raffle"
                try:
                    end_dt = datetime.fromisoformat(end_date)
                    days_left = (end_dt - utc_now()).days
                    time_left = get_text(user_id, "contest_time_left").format(days_left) if days_left > 0 else get_text(user_id, "contest_expired_label")
                except:
                    time_left = "📅 تاريخ غير صحيح"
                    days_left = 0
                try:
                    participated = await db_get_user_participation(user_id, cid)
                except Exception as e:
                    logger.error(f"Error in db_get_user_participation for user {user_id} and contest {cid}: {e}")
                    participated = None
                status_icon = "✅" if participated else "📝"
                type_icon = "📝" if contest_type == "quiz" else "🎲" if contest_type == "raffle" else "🗳️" if contest_type == "vote" else "📤"
                text += f"📌 **{title}** {type_icon}\n"
                text += f"📝 {(desc)[:100]}{'...' if len(desc) > 100 else ''}\n"
                text += f"🎁 الجائزة: {prize}\n"
                text += f"👥 المشاركون: {participants}\n"
                text += f"🕐 {time_left}\n"
                text += f"━━━━━━━━━━━━━━━━━━━━━━\n"
                if not participated and days_left > 0:
                    keyboard.append([InlineKeyboardButton(f"{status_icon} شارك في {title[:20]}", callback_data=f"{CallbackData.CONTEST_JOIN_PREFIX}{cid}")])
            except Exception as e:
                logger.error(f"Error processing contest: {e}")
                continue
        keyboard.append([InlineKeyboardButton("🏆 الفائزون السابقون", callback_data=CallbackData.CONTEST_WINNERS)])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
        if update.callback_query:
            try:
                await safe_edit_markdown(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard))
            except:
                await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await safe_send_markdown(context.bot, user_id, text, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        error_id = log_error(e, {"user_id": update.effective_user.id if update and update.effective_user else None, "chat_id": update.effective_chat.id if update and update.effective_chat else None})
        msg = f"❌ حدث خطأ أثناء تحميل المسابقات (الرمز: `{error_id}`).\nيرجى المحاولة مرة أخرى لاحقاً."
        try:
            if update.callback_query:
                await safe_edit_markdown(update.callback_query, msg)
            else:
                await safe_send_markdown(context.bot, user_id, msg)
        except:
            try:
                if update.callback_query:
                    await update.callback_query.edit_message_text("❌ حدث خطأ أثناء تحميل المسابقات.")
                else:
                    await context.bot.send_message(chat_id=user_id, text="❌ حدث خطأ أثناء تحميل المسابقات.")
            except:
                pass

async def contests_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except:
            pass
    await contests_command_handler(update, context)

async def contest_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    try:
        await query.answer()
    except:
        pass
    user_id = update.effective_user.id
    try:
        contest_id = int(query.data.split(":")[-1])
    except (ValueError, IndexError):
        try:
            await query.edit_message_text("❌ بيانات غير صالحة.")
        except:
            pass
        return
    try:
        contest = await db_get_contest(contest_id)
        if not contest:
            try:
                await query.edit_message_text("❌ المسابقة غير موجودة.")
            except:
                pass
            return
        if contest["status"] != "active":
            try:
                await query.edit_message_text("❌ هذه المسابقة غير متاحة حالياً.")
            except:
                pass
            return
        try:
            end_date = datetime.fromisoformat(contest["end_date"])
            if end_date < utc_now():
                try:
                    await query.edit_message_text("❌ هذه المسابقة قد انتهت.")
                except:
                    pass
                return
        except:
            pass
        participation = await db_get_user_participation(user_id, contest_id)
        if participation:
            try:
                await query.edit_message_text(get_text(user_id, "contest_participated"))
            except:
                pass
            return
        context.user_data["contest_join_id"] = contest_id
        context.user_data["state"] = "WAITING_CONTEST_ANSWER"
        msg = f"📝 **المشاركة في المسابقة: {contest['title']}**\n\n📌 أرسل إجابتك (نص) أو اضغط /skip للمشاركة بدون إجابة.\n⏳ يمكنك تعديل إجابتك قبل انتهاء المسابقة.\n📝 نوع المسابقة: {contest.get('contest_type', 'raffle')}"
        try:
            await query.edit_message_text(msg, parse_mode="MarkdownV2")
        except:
            await query.edit_message_text(msg)
    except Exception as e:
        error_id = log_error(e, {"user_id": user_id, "contest_id": contest_id})
        try:
            await query.edit_message_text(f"❌ حدث خطأ أثناء المشاركة (الرمز: `{error_id}`).")
        except:
            pass

async def contest_winners_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        if query:
            await query.answer()
    except:
        pass
    user_id = update.effective_user.id
    try:
        winners = await db_get_contest_winners(limit=10)
        if not winners:
            if query:
                try:
                    await query.edit_message_text(get_text(user_id, "no_winners"))
                except:
                    pass
            else:
                await safe_send_markdown(context.bot, user_id, get_text(user_id, "no_winners"))
            return
        text = get_text(user_id, "contest_winners_title")
        for contest_id, title, prize, winner_id, announced_at in winners:
            try:
                winner = await context.bot.get_chat(winner_id)
                winner_name = winner.first_name or str(winner_id)
            except:
                winner_name = str(winner_id)
            try:
                announced_dt = datetime.fromisoformat(announced_at)
                announced_mecca = utc_to_mecca(announced_dt)
                date_str = announced_mecca.strftime("%Y-%m-%d")
            except:
                date_str = announced_at[:10] if announced_at else "?"
            text += f"📌 **{title}**\n🎁 {prize}\n👤 {winner_name}\n📅 {date_str}\n━━━━━━━━━━━━━━━━━━━━━━\n"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 تحديث", callback_data=CallbackData.CONTEST_WINNERS)], [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.CONTESTS_BACK)]])
        if query:
            try:
                await safe_edit_markdown(query, text, reply_markup=keyboard)
            except:
                await query.edit_message_text(text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)
    except Exception as e:
        error_id = log_error(e, {"user_id": user_id})
        if query:
            try:
                await query.edit_message_text(f"❌ حدث خطأ أثناء عرض الفائزين (الرمز: `{error_id}`).")
            except:
                pass
        else:
            await safe_send_markdown(context.bot, user_id, f"❌ حدث خطأ أثناء عرض الفائزين (الرمز: `{error_id}`).")

async def contests_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await contests_command_handler(update, context)

async def create_contest_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text(get_text(user_id, "admin_only"))
        return
    context.user_data["state"] = "WAITING_CONTEST_TITLE"
    await update.message.reply_text(get_text(user_id, "create_contest_title"))

async def declare_winner_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text(get_text(user_id, "admin_only"))
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(get_text(user_id, "declare_winner_usage"))
        return
    try:
        contest_id = int(args[0])
        winner_id = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ معرف غير صالح.")
        return
    contest = await db_get_contest(contest_id)
    if not contest:
        await update.message.reply_text(get_text(user_id, "contest_not_found"))
        return
    if contest["status"] != "active":
        await update.message.reply_text(get_text(user_id, "contest_expired"))
        return
    participation = await db_get_user_participation(winner_id, contest_id)
    if not participation:
        await update.message.reply_text(get_text(user_id, "contest_not_participant"))
        return
    success = await db_set_contest_winner(contest_id, winner_id)
    if success:
        await update.message.reply_text(get_text(user_id, "contest_declared").format(contest["title"], winner_id, contest["prize"]))
        try:
            await context.bot.send_message(winner_id, get_text(winner_id, "contest_winner_notification").format(contest["title"], contest["prize"]))
        except:
            pass
        level_data = await db_get_user_level(winner_id)
        await db_update_user_level(winner_id, level_data["points"] + 50, level_data["level"])
    else:
        await update.message.reply_text(get_text(user_id, "contest_declared_error"))

async def admin_create_contest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except:
            pass
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        if query:
            try:
                await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
            except:
                pass
        return
    context.user_data["state"] = "WAITING_CONTEST_TITLE"
    msg = "📝 **إنشاء مسابقة جديدة**\n\nأرسل **عنوان** المسابقة:"
    if query:
        try:
            await query.edit_message_text(msg, parse_mode="MarkdownV2")
        except:
            try:
                await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="MarkdownV2")
            except:
                pass
    else:
        try:
            await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="MarkdownV2")
        except:
            pass

async def admin_declare_winner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except:
            pass
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        if query:
            try:
                await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
            except:
                pass
        return
    msg = "📝 **إعلان فائز في مسابقة**\n\nاستخدم الأمر:\n`/declare_winner معرف_المسابقة معرف_المستخدم`\n\nمثال: `/declare_winner 5 123456789`\n\n📌 لعرض المسابقات النشطة استخدم `/contests`"
    if query:
        try:
            await query.edit_message_text(msg, parse_mode="MarkdownV2")
        except:
            try:
                await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="MarkdownV2")
            except:
                pass
    else:
        try:
            await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="MarkdownV2")
        except:
            pass

async def lang_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if query:
        lang = query.data.split("_")[1] if "_" in query.data else None
    else:
        lang = context.user_data.get("lang_set")
    if not lang:
        if query:
            await query.edit_message_text("❌ لم يتم تحديد اللغة")
        else:
            await update.message.reply_text("❌ لم يتم تحديد اللغة")
        return
    await set_user_language(uid, lang)
    lang_names = {"ar": "العربية 🇸🇦", "en": "English 🇬🇧", "fr": "Français 🇫🇷", "tr": "Türkçe 🇹🇷", "zh": "中文 🇨🇳", "ru": "Русский 🇷🇺", "de": "Deutsch 🇩🇪", "es": "Español 🇪🇸", "it": "Italiano 🇮🇹", "pt": "Português 🇵🇹", "ja": "日本語 🇯🇵", "ko": "한국어 🇰🇷"}
    lang_name = lang_names.get(lang, lang)
    await main_menu_callback(update, context)

async def handle_text_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    data = query.data if query else context.user_data.get("text_callback_data")
    if not data:
        return
    if data == "rank":
        data_rank = await get_rank(uid)
        points = data_rank["points"]
        level = data_rank["level"]
        next_points = LEVEL_REQUIREMENTS.get(level + 1, points)
        points_needed = next_points - points if next_points > points else 0
        text = f"📊 **رتبتك الحالية**\n━━━━━━━━━━━━━━\n👤 {query.from_user.first_name if query else '👤'}\n⭐ **المستوى:** {level}\n📈 **النقاط:** {points}\n📌 **المتبقي للمستوى التالي:** {points_needed}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]])
        if query:
            await safe_edit_markdown(query, text, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=kb)
    elif data == "top":
        top_users = await get_top_users(10)
        if not top_users:
            msg = "📭 لا توجد نقاط مسجدة بعد."
            if query:
                await query.edit_message_text(msg)
            else:
                await update.message.reply_text(msg)
            return
        text = "🏆 **أفضل 10 مستخدمين**\n━━━━━━━━━━━━━━\n"
        for idx, (uid_user, points, level) in enumerate(top_users, 1):
            try:
                user = await context.bot.get_chat(uid_user)
                name = user.first_name or str(uid_user)
            except:
                name = str(uid_user)
            text += f"{idx}. {name} → المستوى {level} ({points} نقطة)\n"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]])
        if query:
            await safe_edit_markdown(query, text, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=kb)
    elif data == "schedule_post":
        context.user_data["state"] = "WAITING_SCHEDULE_POST"
        msg = "📝 **جدولة منشور جديد**\n\nأرسل المنشور بالصيغة التالية:\n`YYYY-MM-DD HH:MM نص المنشور`\n\nمثال: `2024-12-31 20:00 مرحباً بالجميع!`\n\n🕐 الوقت بتوقيت مكة المكرمة"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]])
        if query:
            await query.edit_message_text(msg, parse_mode="MarkdownV2", reply_markup=kb)
        else:
            await update.message.reply_text(msg, parse_mode="MarkdownV2", reply_markup=kb)
    elif data == "language":
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("العربية 🇸🇦", callback_data="lang_ar"), InlineKeyboardButton("English 🇬🇧", callback_data="lang_en")], [InlineKeyboardButton("Français 🇫🇷", callback_data="lang_fr"), InlineKeyboardButton("Türkçe 🇹🇷", callback_data="lang_tr")], [InlineKeyboardButton("中文 🇨🇳", callback_data="lang_zh"), InlineKeyboardButton("Русский 🇷🇺", callback_data="lang_ru")], [InlineKeyboardButton("Deutsch 🇩🇪", callback_data="lang_de"), InlineKeyboardButton("Español 🇪🇸", callback_data="lang_es")], [InlineKeyboardButton("Italiano 🇮🇹", callback_data="lang_it"), InlineKeyboardButton("Português 🇵🇹", callback_data="lang_pt")], [InlineKeyboardButton("日本語 🇯🇵", callback_data="lang_ja"), InlineKeyboardButton("한국어 🇰🇷", callback_data="lang_ko")], [InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]])
        if query:
            await query.edit_message_text(get_text(uid, "welcome"), reply_markup=keyboard)
        else:
            await update.message.reply_text(get_text(uid, "welcome"), reply_markup=keyboard)
    elif data == CallbackData.CONTESTS_MENU:
        await contests_command_handler(update, context)

async def advanced_actions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("advanced_chat_id")
    if chat_id == 0:
        if query:
            await query.edit_message_text("⚠️ يرجى اختيار مجموعة أولاً باستخدام أمر /security")
        else:
            await update.message.reply_text("⚠️ يرجى اختيار مجموعة أولاً باستخدام أمر /security")
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    msg = "🛠️ **الإجراءات المتقدمة للمجموعة**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر الإجراء المطلوب:"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🛑 حظر", callback_data=f"{CallbackData.GROUP_ACTION_BAN}:{chat_id}"), InlineKeyboardButton("🔇 كتم", callback_data=f"{CallbackData.GROUP_ACTION_MUTE}:{chat_id}")], [InlineKeyboardButton("⚠️ تحذير", callback_data=f"{CallbackData.GROUP_ACTION_WARN}:{chat_id}"), InlineKeyboardButton("👢 طرد", callback_data=f"{CallbackData.GROUP_ACTION_KICK}:{chat_id}")], [InlineKeyboardButton("🔒 تقييد", callback_data=f"{CallbackData.GROUP_ACTION_RESTRICT}:{chat_id}"), InlineKeyboardButton("📌 تثبيت", callback_data=f"{CallbackData.GROUP_ACTION_PIN}:{chat_id}")], [InlineKeyboardButton("🔓 إلغاء حظر", callback_data=f"{CallbackData.GROUP_ACTION_UNBAN}:{chat_id}"), InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
    if query:
        await safe_edit_markdown(query, msg, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, msg, reply_markup=kb)

async def group_action_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("advanced_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    context.user_data["state"] = "WAITING_BAN_USER"
    context.user_data["advanced_chat_id"] = chat_id
    msg = "🚫 **حظر مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /ban\n\nيمكنك إضافة سبب بعد المعرف: `/ban 123456789 السبب`"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_mute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("advanced_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    msg = "🔇 **كتم مستخدم**\n\nاختر مدة الكتم:"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏱️ 5 دقائق", callback_data=f"adv_mute_duration:5:{chat_id}"), InlineKeyboardButton("⏱️ 30 دقيقة", callback_data=f"adv_mute_duration:30:{chat_id}")], [InlineKeyboardButton("⏱️ 1 ساعة", callback_data=f"adv_mute_duration:60:{chat_id}"), InlineKeyboardButton("⏱️ 12 ساعة", callback_data=f"adv_mute_duration:720:{chat_id}")], [InlineKeyboardButton("📆 يوم", callback_data=f"adv_mute_duration:1440:{chat_id}"), InlineKeyboardButton("📆 أسبوع", callback_data=f"adv_mute_duration:10080:{chat_id}")], [InlineKeyboardButton("🔇 كتم دائم", callback_data=f"adv_mute_duration:0:{chat_id}"), InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}")]])
    if query:
        await safe_edit_markdown(query, msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

async def advanced_mute_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    parts = query.data.split(":") if query else context.user_data.get("mute_duration_data", "").split(":")
    if len(parts) == 3:
        minutes = int(parts[1])
        chat_id = int(parts[2])
        uid = update.effective_user.id
        if not await is_authorized_in_group(context.bot, chat_id, uid):
            if query:
                await query.answer(get_text(uid, "admin_only"), show_alert=True)
            else:
                await update.message.reply_text(get_text(uid, "admin_only"))
            return
        context.user_data["mute_minutes"] = minutes
        context.user_data["state"] = "WAITING_MUTE_USER"
        context.user_data["advanced_chat_id"] = chat_id
        if minutes == 0:
            msg = "🔇 **كتم دائم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute\n\nيمكنك إضافة سبب: `/mute 123456789 السبب`"
        elif minutes < 60:
            msg = f"🔇 **كتم {minutes} دقيقة**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute\n\nيمكنك إضافة سبب: `/mute 123456789 السبب`"
        elif minutes < 1440:
            msg = f"🔇 **كتم {minutes // 60} ساعة**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute\n\nيمكنك إضافة سبب: `/mute 123456789 السبب`"
        else:
            msg = f"🔇 **كتم {minutes // 1440} يوم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute\n\nيمكنك إضافة سبب: `/mute 123456789 السبب`"
        if query:
            await safe_edit_markdown(query, msg)
        else:
            await update.message.reply_text(msg)

async def group_action_warn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("advanced_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    context.user_data["state"] = "WAITING_WARN_USER"
    context.user_data["advanced_chat_id"] = chat_id
    msg = "⚠️ **تحذير مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /warn\n\nيمكنك إضافة سبب: `/warn 123456789 السبب`\n\n📌 بعد 3 تحذيرات يتم حظر المستخدم تلقائياً"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_kick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("advanced_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    context.user_data["state"] = "WAITING_KICK_USER"
    context.user_data["advanced_chat_id"] = chat_id
    msg = "👢 **طرد مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /kick\n\nيمكنك إضافة سبب: `/kick 123456789 السبب`"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_restrict_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("advanced_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    context.user_data["state"] = "WAITING_RESTRICT_USER"
    context.user_data["advanced_chat_id"] = chat_id
    msg = "🔒 **تقييد مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /restrict\n\n📌 التقييد يمنع المستخدم من إرسال الصور والفيديوهات والملفات"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_pin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("advanced_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    context.user_data["state"] = "WAITING_PIN_MESSAGE"
    context.user_data["advanced_chat_id"] = chat_id
    msg = "📌 **تثبيت رسالة**\n\nقم بالرد على الرسالة التي تريد تثبيتها ثم أرسل /pin"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_log_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("advanced_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    text = await get_moderation_log(chat_id, 20)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def group_action_unban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("advanced_chat_id")
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))
        return
    context.user_data["state"] = "WAITING_UNBAN_USER"
    context.user_data["advanced_chat_id"] = chat_id
    msg = "🔓 **إلغاء حظر مستخدم**\n\nأرسل معرف المستخدم (user_id) لإلغاء حظره:\n`/unban 123456789`"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def panel_lock_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("panel_chat_id")
    if not chat_id:
        return
    if await is_authorized_in_group(context.bot, chat_id, uid):
        await db_set_chat_lock(chat_id, True, uid)
        if query:
            await safe_edit_markdown(query, get_text(uid, "locked"))
        else:
            await update.message.reply_text(get_text(uid, "locked"))
    else:
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))

async def panel_unlock_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get("panel_chat_id")
    if not chat_id:
        return
    if await is_authorized_in_group(context.bot, chat_id, uid):
        await db_set_chat_lock(chat_id, False)
        if query:
            await safe_edit_markdown(query, get_text(uid, "unlocked"))
        else:
            await update.message.reply_text(get_text(uid, "unlocked"))
    else:
        if query:
            await query.answer(get_text(uid, "admin_only"), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, "admin_only"))

async def panel_close_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.message.delete()

async def check_subscribe_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    enabled = await db_get_force_subscribe_status()
    channel = await db_get_force_subscribe_channel()
    if enabled and channel:
        if await is_user_subscribed(context.bot, uid, channel):
            if query:
                await safe_edit_markdown(query, "✅ تم التحقق! أنت مشترك الآن.")
            else:
                await update.message.reply_text("✅ تم التحقق! أنت مشترك الآن.")
            await main_menu_callback(update, context)
        else:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 اشترك", url=f"https://t.me/{channel.lstrip('@')}"), InlineKeyboardButton("🔄 تأكد", callback_data=CallbackData.CHECK_SUBSCRIBE), InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]])
            if query:
                await safe_edit_markdown(query, f"❌ لم تشترك في @{channel.lstrip('@')}", reply_markup=kb)
            else:
                await update.message.reply_text(f"❌ لم تشترك في @{channel.lstrip('@')}", reply_markup=kb)
    else:
        if query:
            await safe_edit_markdown(query, "⚠️ الاشتراك الإجباري غير مفعل")
        else:
            await update.message.reply_text("⚠️ الاشتراك الإجباري غير مفعل")

async def publish_all_channels_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    channels = await db_get_channels(uid)
    if not channels:
        if query:
            await query.edit_message_text("📭 لا توجد قنوات للنشر فيها.")
        else:
            await update.message.reply_text("📭 لا توجد قنوات للنشر فيها.")
        return
    if query:
        await query.edit_message_text("📤 جاري النشر في جميع القنوات...")
    else:
        await update.message.reply_text("📤 جاري النشر في جميع القنوات...")
    results = []
    success_count = 0
    fail_count = 0
    no_posts_count = 0
    for ch_db_id, ch_tele_id, ch_name, banned in channels:
        if banned:
            results.append(f"⛔ {ch_name}: قناة محظورة")
            continue
        post = await db_get_next_post(ch_db_id)
        if not post:
            results.append(f"📭 {ch_name}: لا توجد منشورات")
            no_posts_count += 1
            continue
        translation_lang = await get_user_translation_language(uid)
        final_text = post["text"]
        if translation_lang != "off" and final_text:
            try:
                translated = await translate_text(final_text, translation_lang)
                if translated and translated != final_text:
                    final_text = f"{final_text}\n\n🌐 {translated}"
            except:
                pass
        try:
            if post["media_type"] == "photo" and post["media_file_id"]:
                await context.bot.send_photo(ch_tele_id, post["media_file_id"], caption=final_text if final_text else None)
            elif post["media_type"] == "video" and post["media_file_id"]:
                await context.bot.send_video(ch_tele_id, post["media_file_id"], caption=final_text if final_text else None)
            elif post["media_type"] == "document" and post["media_file_id"]:
                await context.bot.send_document(ch_tele_id, post["media_file_id"], caption=final_text if final_text else None)
            elif post["media_type"] == "audio" and post["media_file_id"]:
                await context.bot.send_audio(ch_tele_id, post["media_file_id"], caption=final_text if final_text else None)
            elif post["media_type"] == "voice" and post["media_file_id"]:
                await context.bot.send_voice(ch_tele_id, post["media_file_id"], caption=final_text if final_text else None)
            elif post["media_type"] == "animation" and post["media_file_id"]:
                await context.bot.send_animation(ch_tele_id, post["media_file_id"], caption=final_text if final_text else None)
            else:
                await context.bot.send_message(ch_tele_id, final_text)
            await db_mark_published(post["id"])
            await db_set_last_publish(ch_db_id, utc_now())
            await db_update_next_publish_date(ch_db_id)
            results.append(f"✅ {ch_name}: تم النشر بنجاح")
            success_count += 1
        except Exception as e:
            results.append(f"❌ {ch_name}: {str(e)[:50]}")
            fail_count += 1
        await asyncio.sleep(1)
    summary = f"📊 **نتائج النشر في جميع القنوات**\n━━━━━━━━━━━━━━━━━━━━━━\n✅ نجح: {success_count}\n❌ فشل: {fail_count}\n📭 لا توجد منشورات: {no_posts_count}\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    result_text = summary + "\n".join(results[:20])
    if len(results) > 20:
        result_text += f"\n\n... و {len(results)-20} نتيجة أخرى"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, "back"), callback_data=CallbackData.BACK)]])
    if query:
        await safe_edit_markdown(query, result_text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, result_text, reply_markup=keyboard)

async def channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    try:
        channel_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get("channel_stats_id")
    except:
        channel_db_id = context.user_data.get("channel_stats_id")
    if not channel_db_id:
        if query:
            await query.edit_message_text("⚠️ لم يتم تحديد القناة.")
        else:
            await update.message.reply_text("⚠️ لم يتم تحديد القناة.")
        return
    channels = await db_get_channels(user_id)
    if not any(ch[0] == channel_db_id for ch in channels):
        if query:
            await query.answer("❌ هذه القناة ليست لك", show_alert=True)
        else:
            await update.message.reply_text("❌ هذه القناة ليست لك")
        return
    stats = await db_get_channel_stats(channel_db_id)
    ch_info = await db_get_channel_info(channel_db_id)
    channel_name = ch_info[1] if ch_info else "القناة"
    if stats["total_posts"] == 0:
        text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد منشورات بعد"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{channel_db_id}")], [InlineKeyboardButton("📈 نمو القناة", callback_data=f"{CallbackData.CHANNEL_GROWTH}:{channel_db_id}")], [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
        if query:
            await safe_edit_markdown(query, text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)
        return
    text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📝 إجمالي المنشورات: {stats['total_posts']}\n"
    text += f"✅ المنشورة: {stats['published_posts']}\n"
    text += f"⏳ غير المنشورة: {stats['unpublished_posts']}\n"
    text += f"👁️ إجمالي المشاهدات: {stats['total_views']}\n"
    text += f"📊 متوسط المشاهدات: {stats['avg_views']}\n"
    if stats["last_post_time"]:
        try:
            last_dt = datetime.fromisoformat(stats["last_post_time"])
            last_mecca = utc_to_mecca(last_dt)
            text += f"🕐 آخر نشر: {last_mecca.strftime('%Y-%m-%d %H:%M')}\n"
        except:
            pass
    if stats["first_post_time"]:
        try:
            first_dt = datetime.fromisoformat(stats["first_post_time"])
            first_mecca = utc_to_mecca(first_dt)
            text += f"📅 أول نشر: {first_mecca.strftime('%Y-%m-%d %H:%M')}\n"
        except:
            pass
    text += f"⏱️ متوسط الوقت بين المنشورات: {stats['avg_time_between_posts']} ساعة\n"
    text += f"🕐 أفضل وقت للنشر: {stats['best_publish_hour']}:00\n"
    day_names = ["الأحد", "الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت"]
    text += f"📅 أفضل يوم للنشر: {day_names[stats['best_publish_day']] if stats['best_publish_day'] < 7 else 'غير محدد'}\n"
    text += f"📊 المنشورات اليوم: {stats['published_today']}\n"
    text += f"📊 هذا الأسبوع: {stats['published_this_week']}\n"
    text += f"📊 هذا الشهر: {stats['published_this_month']}\n"
    if stats["most_viewed_post"]:
        text += f"\n🏆 **الأكثر مشاهدة:**\n{stats['most_viewed_post']['text']}\n👁️ {stats['most_viewed_post']['views']} مشاهدة\n"
    if stats["least_viewed_post"]:
        text += f"\n📉 **الأقل مشاهدة:**\n{stats['least_viewed_post']['text']}\n👁️ {stats['least_viewed_post']['views']} مشاهدة\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{channel_db_id}")], [InlineKeyboardButton("📈 نمو القناة", callback_data=f"{CallbackData.CHANNEL_GROWTH}:{channel_db_id}")], [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def channel_growth_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    try:
        channel_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get("channel_stats_id")
    except:
        channel_db_id = context.user_data.get("channel_stats_id")
    if not channel_db_id:
        if query:
            await query.edit_message_text("⚠️ لم يتم تحديد القناة.")
        else:
            await update.message.reply_text("⚠️ لم يتم تحديد القناة.")
        return
    channels = await db_get_channels(user_id)
    if not any(ch[0] == channel_db_id for ch in channels):
        if query:
            await query.answer("❌ هذه القناة ليست لك", show_alert=True)
        else:
            await update.message.reply_text("❌ هذه القناة ليست لك")
        return
    growth = await db_get_channel_growth(channel_db_id, days=30)
    ch_info = await db_get_channel_info(channel_db_id)
    channel_name = ch_info[1] if ch_info else "القناة"
    if not growth["dates"]:
        text = f"📈 **نمو {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\nلا توجد بيانات كافية لعرض النمو."
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.CHANNEL_STATS}:{channel_db_id}")]])
        if query:
            await safe_edit_markdown(query, text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)
        return
    text = f"📈 **نمو {channel_name} (آخر 30 يوم)**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📝 إجمالي المنشورات في الفترة: {growth['total_posts']}\n"
    text += f"👁️ إجمالي المشاهدات: {growth['total_views']}\n"
    text += f"📅 عدد الأيام: {growth['total_days']}\n"
    text += f"📊 متوسط المنشورات يومياً: {growth['total_posts'] / max(1, growth['total_days']):.1f}\n"
    text += f"📊 متوسط المشاهدات يومياً: {growth['total_views'] / max(1, growth['total_days']):.1f}\n"
    text += "\n📅 **التفاصيل اليومية:**\n"
    for i, (date, count, views) in enumerate(zip(growth["dates"], growth["counts"], growth["views"])):
        if i >= 10:
            break
        text += f"• {date}: {count} منشورات، {views} مشاهدة\n"
    if len(growth["dates"]) > 10:
        text += f"\n... و {len(growth['dates']) - 10} أيام أخرى"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📊 العودة للإحصائيات", callback_data=f"{CallbackData.CHANNEL_STATS}:{channel_db_id}")], [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def channel_stats_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await channel_stats_callback(update, context)

async def my_channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    summary = await db_get_channel_stats_summary(user_id)
    if not summary:
        text = "📊 **ملخص قنواتي**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد قنوات مسجلة."
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("➕ إضافة قناة", callback_data=CallbackData.CHANNELS_ADD)], [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
        if query:
            await safe_edit_markdown(query, text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)
        return
    text = f"📊 **ملخص قنواتي**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📡 عدد القنوات: {summary['total_channels']}\n"
    text += f"✅ القنوات النشطة: {summary['active_channels']}\n"
    text += f"📝 إجمالي المنشورات: {summary['total_posts']}\n"
    text += f"✅ المنشورة: {summary['total_published']}\n"
    text += f"👁️ إجمالي المشاهدات: {summary['total_views']}\n"
    text += f"📊 متوسط المشاهدات لكل قناة: {summary['avg_views_per_channel']}\n"
    if summary["best_channel"]:
        text += f"\n🏆 **أفضل قناة:**\n"
        text += f"• {summary['best_channel']['name']}\n"
        text += f"• مشاهدات: {summary['best_channel']['views']}\n"
        text += f"• منشورات: {summary['best_channel']['posts']}\n"
        text += f"• متوسط المشاهدات: {summary['best_channel']['avg_views']}\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📡 عرض القنوات", callback_data=CallbackData.CHANNELS_MY)], [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def syncgroup_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    chat_name = update.effective_chat.title or "بدون اسم"
    user_id = update.effective_user.id
    await db_register_group(chat_id, chat_name, user_id, update.effective_chat.username)
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms["can_act"]:
        await update.message.reply_text(f"⚠️ **تنبيه:**\n{bot_perms['reason']}\n\nيرجى منح البوت الصلاحيات المطلوبة.")
        return
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ["creator", "administrator"]:
            await db_register_hidden_owner_group(chat_id, user_id)
            await invalidate_user_cache(user_id=user_id, chat_id=chat_id)
            await update.message.reply_text(f"✅ **تم تسجيلك كمالك مخفي لهذه المجموعة.**\n\n📌 اسم المجموعة: {chat_name}\n🆔 المعرف: {chat_id}\n👤 المستخدم: {user_id}\n\n🔐 استخدم /security لإعدادات الأمان\n🛠️ استخدم /panel للوحة التحكم")
        else:
            await update.message.reply_text(f"⚠️ **عذراً، أنت لست مشرفاً في هذه المجموعة.**\n\n📌 **للاستفادة من ميزات البوت المتقدمة، تواصل معنا على الخاص:**\n👉 @{BOT_USERNAME}\n\n💡 **ماذا يمكنك أن تفعل مع البوت؟**\n• إدارة قنواتك ونشر المنشورات تلقائياً\n• حماية المجموعات من الروابط والمزعجين\n• إحصائيات متقدمة ومخططات نمو\n• نظام مسابقات متكامل\n• وأكثر من 200 ميزة! 🚀\n\n🔗 **ادعُ البوت إلى مجموعتك:**\nhttps://t.me/{BOT_USERNAME}?startgroup")
            return
    except Exception as e:
        await update.message.reply_text(f"⚠️ تعذر التحقق من صلاحياتك: {e}")
        return
    await update.message.reply_text(f"✅ **تم تفعيل المجموعة بنجاح!**\n\n📌 اسم المجموعة: {chat_name}\n🆔 المعرف: {chat_id}\n👤 المضافة بواسطة: {user_id}\n\n🔐 استخدم /security لإعدادات الأمان\n🛠️ استخدم /panel للوحة التحكم", parse_mode="MarkdownV2")

async def register_hidden_owner_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    user = update.effective_user
    if user is None:
        return
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ يعمل فقط في المجموعات")
        return
    chat_id = chat.id
    user_id = user.id
    if not await is_telegram_admin(context.bot, chat_id, user_id, update):
        await update.message.reply_text(get_text(user_id, "admin_only"))
        return
    if await db_is_hidden_owner(chat_id, user_id):
        await update.message.reply_text(get_text(user_id, "hidden_owner_already"))
        return
    await db_register_hidden_owner_group(chat_id, user_id)
    await invalidate_user_cache(user_id=user_id, chat_id=chat_id)
    await update.message.reply_text(get_text(user_id, "hidden_owner_registered"))

async def add_hidden_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_telegram_admin(context.bot, chat_id, user_id, update) and not await db_is_hidden_owner(chat_id, user_id):
        await update.message.reply_text(get_text(user_id, "admin_only"))
        return
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("📝 **الاستخدام:**\n/add_hidden_admin معرف_المستخدم\n\nمثال: `/add_hidden_admin 123456789`")
        return
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح!")
        return
    if target_id == PRIMARY_OWNER_ID:
        await update.message.reply_text("❌ لا يمكن إضافة المطور الأساسي كمشرف مخفي!")
        return
    if target_id == user_id:
        await update.message.reply_text("❌ لا يمكن إضافة نفسك كمشرف مخفي!")
        return
    try:
        member = await context.bot.get_chat_member(chat_id, target_id)
        if member.status in ["left", "kicked"]:
            await update.message.reply_text("❌ المستخدم ليس في المجموعة!")
            return
    except Exception as e:
        await update.message.reply_text(f"❌ لا يمكن العثور على المستخدم: {e}")
        return
    try:
        user = await context.bot.get_chat(target_id)
        if user.is_bot:
            await update.message.reply_text("❌ لا يمكن إضافة بوت كمشرف مخفي!")
            return
    except:
        pass
    if await db_is_hidden_admin(chat_id, target_id):
        await update.message.reply_text(f"⚠️ المستخدم `{target_id}` مشرف مخفي بالفعل!")
        return
    success = await db_add_hidden_admin(chat_id, target_id, user_id)
    if success:
        await invalidate_user_cache(user_id=target_id, chat_id=chat_id)
        await update.message.reply_text(get_text(user_id, "hidden_admin_added").format(target_id))
        await security_audit.log("HIDDEN_ADMIN_ADDED", user_id, {"chat_id": chat_id, "target": target_id}, "HIGH")
    else:
        await update.message.reply_text("❌ فشل إضافة المشرف المخفي!")

async def remove_hidden_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_telegram_admin(context.bot, chat_id, user_id, update) and not await db_is_hidden_owner(chat_id, user_id):
        await update.message.reply_text(get_text(user_id, "admin_only"))
        return
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("📝 **الاستخدام:**\n/remove_hidden_admin معرف_المستخدم\n\nمثال: `/remove_hidden_admin 123456789`")
        return
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح!")
        return
    if target_id == PRIMARY_OWNER_ID:
        await update.message.reply_text("❌ لا يمكن إزالة المطور الأساسي!")
        return
    if not await db_is_hidden_admin(chat_id, target_id):
        await update.message.reply_text(f"⚠️ المستخدم `{target_id}` ليس مشرفاً مخفياً!")
        return
    success = await db_remove_hidden_admin(chat_id, target_id)
    if success:
        await invalidate_user_cache(user_id=target_id, chat_id=chat_id)
        await update.message.reply_text(get_text(user_id, "hidden_admin_removed").format(target_id))
        await security_audit.log("HIDDEN_ADMIN_REMOVED", user_id, {"chat_id": chat_id, "target": target_id}, "HIGH")
    else:
        await update.message.reply_text("❌ فشل إزالة المشرف المخفي!")

async def list_hidden_admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, "admin_only"))
        return
    admins = await db_get_hidden_admins(chat_id)
    if not admins:
        await update.message.reply_text(get_text(user_id, "no_hidden_admins"))
        return
    text = get_text(user_id, "hidden_admin_list").format("")
    for admin in admins:
        text += f"👤 المستخدم: `{admin['admin_id']}`\n"
        text += f"➕ أضيف بواسطة: `{admin['added_by']}`\n"
        text += f"🕐 التاريخ: {admin['added_at'][:16]}\n"
        text += "━━━━━━━━━━━━━━━━━━━━━━\n"
    await update.message.reply_text(text, parse_mode="MarkdownV2")

async def update_admins_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_telegram_admin(context.bot, chat_id, user_id, update):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms["can_act"]:
        await update.message.reply_text(f"⚠️ **تنبيه:**\n{bot_perms['reason']}\n\nيرجى منح البوت الصلاحيات المطلوبة.")
        return
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        if not admins:
            await update.message.reply_text("❌ لا يمكن جلب قائمة المشرفين.")
            return
        updated_count = 0
        owner_found = False
        for admin in admins:
            admin_user = admin.user
            admin_id = admin_user.id
            if admin_user.is_bot:
                continue
            if admin.status == "creator":
                if not await db_is_hidden_owner(chat_id, admin_id):
                    await db_register_hidden_owner_group(chat_id, admin_id)
                    updated_count += 1
                    owner_found = True
                    logger.info(f"👑 Registered owner {admin_id} as hidden owner in chat {chat_id}")
            elif admin.status == "administrator":
                if not await db_is_hidden_admin(chat_id, admin_id) and admin_id != PRIMARY_OWNER_ID:
                    await db_add_hidden_admin(chat_id, admin_id, user_id)
                    updated_count += 1
                    logger.info(f"🔒 Registered admin {admin_id} as hidden admin in chat {chat_id}")
        if not owner_found:
            try:
                member = await context.bot.get_chat_member(chat_id, user_id)
                if member.status in ["creator", "administrator"]:
                    if not await db_is_hidden_owner(chat_id, user_id):
                        await db_register_hidden_owner_group(chat_id, user_id)
                        updated_count += 1
                        logger.info(f"👑 Registered user {user_id} as hidden owner in chat {chat_id}")
            except:
                pass
        await invalidate_user_cache(chat_id=chat_id)
        if updated_count > 0:
            await update.message.reply_text(get_text(user_id, "update_admins_success").format(updated_count), parse_mode="MarkdownV2")
        else:
            await update.message.reply_text(get_text(user_id, "update_admins_no_changes"), parse_mode="MarkdownV2")
        await security_audit.log("ADMINS_UPDATED", user_id, {"chat_id": chat_id, "updated_count": updated_count}, "HIGH")
    except Exception as e:
        error_id = log_error(e, {"user_id": user_id, "chat_id": chat_id, "action": "update_admins"})
        await update.message.reply_text(f"{get_text(user_id, 'update_admins_error')}\n\nالرمز: `{error_id}`", parse_mode="MarkdownV2")

async def pre_checkout_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("sub_"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="بيانات غير صالحة")

async def successful_payment_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.effective_user is None:
        return
    uid = update.effective_user.id
    payment = update.message.successful_payment
    try:
        parts = payment.invoice_payload.split("_")
        days = int(parts[1]) if len(parts) >= 2 else 30
    except:
        days = 30
    await db_activate_subscription(uid, days)
    await update.message.reply_text(f"✅ **تم تفعيل اشتراكك لمدة {days} يوماً!**\nشكراً لدعمك ❤️", parse_mode="MarkdownV2")

async def on_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return
    bot_id = context.bot.id
    chat = update.effective_chat
    inviter = update.effective_user
    if chat.type not in ["group", "supergroup"]:
        return
    for member in update.message.new_chat_members:
        if member.id == bot_id:
            added_by_id = inviter.id if inviter else 0
            chat_name = chat.title or "بدون اسم"
            await db_register_group(chat.id, chat_name, added_by_id, chat.username)
            chat_type_name = "مجموعة" if chat.type == "group" else "سوبر جروب"
            await db_register_hidden_owner_group(chat.id, added_by_id)
            await invalidate_user_cache(user_id=added_by_id, chat_id=chat.id)
            logger.info(f"🔒 Registered inviter {added_by_id} as hidden owner for chat {chat.id} (silent registration)")
            owner_info = await detect_owner_type(context.bot, chat.id)
            if owner_info.get("user_id") and owner_info["user_id"] != added_by_id:
                await db_register_hidden_owner_group(chat.id, owner_info["user_id"])
                await invalidate_user_cache(user_id=owner_info["user_id"], chat_id=chat.id)
                logger.info(f"👑 Registered actual owner {owner_info['user_id']} also as hidden owner for chat {chat.id} (silent registration)")
            await send_addition_report(context.bot, inviter, chat, chat_type_name)
            try:
                msg = "✅ **تم تفعيل البوت في المجموعة**\n\n📌 استخدم /panel للوحة التحكم"
                await safe_send_markdown(context.bot, chat.id, msg)
            except:
                pass
            break

async def track_chat_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if not result:
        return
    new_status = result.new_chat_member.status
    old_status = result.old_chat_member.status
    if new_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
        is_new = old_status in [ChatMember.LEFT, ChatMember.BANNED, ChatMember.RESTRICTED]
        if is_new:
            chat = result.chat
            adder = result.from_user
            if chat.type == "channel":
                await db_register_channel(chat.id, chat.title or "بدون اسم", adder.id)
                chat_type_name = "قناة"
            elif chat.type in ["group", "supergroup"]:
                await db_register_group(chat.id, chat.title or "بدون اسم", adder.id, chat.username)
                chat_type_name = "مجموعة" if chat.type == "group" else "سوبر جروب"
                await db_register_hidden_owner_group(chat.id, adder.id)
                await invalidate_user_cache(user_id=adder.id, chat_id=chat.id)
                logger.info(f"🔒 Silent registration for adder {adder.id} as hidden owner for chat {chat.id}")
            else:
                return
            await send_addition_report(context.bot, adder, chat, chat_type_name)

async def track_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if not result or result.chat.type not in ["group", "supergroup"]:
        return
    settings = await db_get_security_settings(result.chat.id)
    if result.new_chat_member.status == "member" and result.old_chat_member.status in ["left", "kicked"]:
        if settings.get("welcome_enabled"):
            user = result.new_chat_member.user
            msg = settings.get("welcome_text", "مرحباً {user} في {chat} 🤍")
            msg = msg.replace("{user}", user.full_name or user.first_name).replace("{chat}", result.chat.title)
            try:
                await safe_send_markdown(context.bot, result.chat.id, msg)
            except:
                pass
    elif result.old_chat_member.status == "member" and result.new_chat_member.status in ["left", "kicked"]:
        if settings.get("goodbye_enabled"):
            user = result.old_chat_member.user
            msg = settings.get("goodbye_text", "وداعاً {user} 👋")
            msg = msg.replace("{user}", user.full_name or user.first_name).replace("{chat}", result.chat.title)
            try:
                await safe_send_markdown(context.bot, result.chat.id, msg)
            except:
                pass

async def send_addition_report(bot, adder, chat, chat_type_name):
    try:
        if adder:
            await bot.send_message(chat_id=adder.id, text=f"✅ **تم إضافة البوت إلى {chat_type_name}**\n\n📌 الاسم: {chat.title}\n🆔 المعرف: {chat.id}\n👤 أضيف بواسطة: {adder.full_name or adder.first_name or adder.id}\n\n🔒 **تم تسجيلك كمالك مخفي تلقائياً**\n🔐 استخدم /security لإعدادات الأمان\n🛠️ استخدم /panel للوحة التحكم", parse_mode="MarkdownV2")
    except:
        pass

async def detect_owner_type(bot, chat_id):
    try:
        admins = await bot.get_chat_administrators(chat_id)
        for admin in admins:
            if admin.status == "creator":
                return {"is_hidden": False, "user_id": admin.user.id}
        return {"is_hidden": True, "user_id": None}
    except:
        return {"is_hidden": True, "user_id": None}

async def language_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("العربية 🇸🇦", callback_data="lang_ar"), InlineKeyboardButton("English 🇬🇧", callback_data="lang_en")], [InlineKeyboardButton("Français 🇫🇷", callback_data="lang_fr"), InlineKeyboardButton("Türkçe 🇹🇷", callback_data="lang_tr")], [InlineKeyboardButton("中文 🇨🇳", callback_data="lang_zh"), InlineKeyboardButton("Русский 🇷🇺", callback_data="lang_ru")], [InlineKeyboardButton("Deutsch 🇩🇪", callback_data="lang_de"), InlineKeyboardButton("Español 🇪🇸", callback_data="lang_es")], [InlineKeyboardButton("Italiano 🇮🇹", callback_data="lang_it"), InlineKeyboardButton("Português 🇵🇹", callback_data="lang_pt")], [InlineKeyboardButton("日本語 🇯🇵", callback_data="lang_ja"), InlineKeyboardButton("한국어 🇰🇷", callback_data="lang_ko")]])
    await update.message.reply_text(get_text(user_id, "welcome"), reply_markup=keyboard)

async def security_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type in ["group", "supergroup"]:
        chat_id = update.effective_chat.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await update.message.reply_text(get_text(user_id, "admin_only"))
            return
        await security_select_group_callback(update, context)
        return
    groups = await db_get_user_groups(user_id)
    if not groups:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("➕ أضف البوت إلى مجموعة", url=f"https://t.me/{BOT_USERNAME}?startgroup")], [InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS)], [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
        text = """🔐 **إعدادات الأمان**

⚠️ لم يتم العثور على مجموعات.

📌 **لتفعيل إعدادات الأمان والإجراءات المتقدمة:**
1. أضف البوت إلى مجموعتك
2. اجعل البوت مشرفاً
3. استخدم الأمر /syncgroup في المجموعة
4. ثم عد إلى الخاص واضغط على تحديث
5. إذا كنت مالكاً مخفياً، استخدم الأمر /register_hidden_owner في المجموعة"""
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)
        return
    keyboard = []
    for chat_id, chat_name, username, banned in groups:
        name = chat_name[:40] + "..." if len(chat_name) > 43 else chat_name
        keyboard.append([InlineKeyboardButton(f"📌 {name}", callback_data=f"{CallbackData.SECURITY_SELECT_GROUP}{chat_id}")])
    keyboard.append([InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS)])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    text = """🔐 **إعدادات الأمان والإجراءات المتقدمة**

📌 اختر المجموعة التي تريد إدارة إعداداتها:

⚠️ ملاحظة: يجب أن يكون البوت مشرفاً في المجموعة
🔒 للمالك المخفي: استخدم /register_hidden_owner في المجموعة أولاً"""
    await safe_send_markdown(context.bot, user_id, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def trial_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await trial_callback(update, context)

async def subscribe_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscribe_menu_callback(update, context)

async def help_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(get_text(user_id, "help"), parse_mode="MarkdownV2")

async def support_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data["support_mode"] = True
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📝 كتابة تذكرة", callback_data=CallbackData.SUPPORT_TICKET)], [InlineKeyboardButton("❓ المساعدة", callback_data=CallbackData.SUPPORT_HELP)], [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
    await update.message.reply_text(get_text(user_id, "support_welcome"), reply_markup=keyboard)

async def support_reply_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != PRIMARY_OWNER_ID and not await is_bot_admin(update.effective_user.id):
        await update.message.reply_text(get_text(update.effective_user.id, "admin_only"))
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📝 **الاستخدام:**\n`/support_reply user_id نص الرد`", parse_mode="MarkdownV2")
        return
    try:
        target_user_id = int(args[0])
        reply_text = " ".join(args[1:])
        ticket_id = await db_get_last_ticket_id_for_user(target_user_id)
        if ticket_id:
            await db_mark_ticket_replied(ticket_id)
        await context.bot.send_message(chat_id=target_user_id, text=f"📬 **رد على تذكرتك:**\n━━━━━━━━━━━━━━━━━━━━━━\n{reply_text}", parse_mode="MarkdownV2")
        await update.message.reply_text(f"✅ تم إرسال الرد إلى المستخدم {target_user_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل الإرسال: {e}")

async def rank_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_text_callbacks(update, context)

async def top_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_text_callbacks(update, context)

async def developer_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await developer_callback(update, context)

async def updates_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await updates_callback(update, context)

async def stats_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    uid = update.effective_user.id
    if not await ensure_force_subscribe(update, context, uid):
        return
    active = context.user_data.get("active_channel") or await db_get_active_channel(uid)
    if not active:
        await update.message.reply_text("⚠️ يرجى اختيار قناة أولاً")
        return
    stats = await db_get_channel_stats(active)
    ch_info = await db_get_channel_info(active)
    channel_name = ch_info[1] if ch_info else "القناة"
    if stats["total_posts"] == 0:
        text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد منشورات بعد"
        await safe_send_markdown(context.bot, uid, text)
        return
    text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📝 إجمالي المنشورات: {stats['total_posts']}\n"
    text += f"✅ المنشورة: {stats['published_posts']}\n"
    text += f"⏳ غير المنشورة: {stats['unpublished_posts']}\n"
    text += f"👁️ إجمالي المشاهدات: {stats['total_views']}\n"
    text += f"📊 متوسط المشاهدات: {stats['avg_views']}\n"
    if stats["last_post_time"]:
        try:
            last_dt = datetime.fromisoformat(stats["last_post_time"])
            last_mecca = utc_to_mecca(last_dt)
            text += f"🕐 آخر نشر: {last_mecca.strftime('%Y-%m-%d %H:%M')}\n"
        except:
            pass
    if stats["first_post_time"]:
        try:
            first_dt = datetime.fromisoformat(stats["first_post_time"])
            first_mecca = utc_to_mecca(first_dt)
            text += f"📅 أول نشر: {first_mecca.strftime('%Y-%m-%d %H:%M')}\n"
        except:
            pass
    text += f"⏱️ متوسط الوقت بين المنشورات: {stats['avg_time_between_posts']} ساعة\n"
    text += f"🕐 أفضل وقت للنشر: {stats['best_publish_hour']}:00\n"
    day_names = ["الأحد", "الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت"]
    text += f"📅 أفضل يوم للنشر: {day_names[stats['best_publish_day']] if stats['best_publish_day'] < 7 else 'غير محدد'}\n"
    text += f"📊 المنشورات اليوم: {stats['published_today']}\n"
    text += f"📊 هذا الأسبوع: {stats['published_this_week']}\n"
    text += f"📊 هذا الشهر: {stats['published_this_month']}\n"
    if stats["most_viewed_post"]:
        text += f"\n🏆 **الأكثر مشاهدة:**\n{stats['most_viewed_post']['text']}\n👁️ {stats['most_viewed_post']['views']} مشاهدة\n"
    if stats["least_viewed_post"]:
        text += f"\n📉 **الأقل مشاهدة:**\n{stats['least_viewed_post']['text']}\n👁️ {stats['least_viewed_post']['views']} مشاهدة\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{active}")], [InlineKeyboardButton("📈 نمو القناة", callback_data=f"{CallbackData.CHANNEL_GROWTH}:{active}")], [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
    await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def lock_chat_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat is None or update.effective_user is None:
        return
    user_id = update.effective_user.id
    chat_id = None
    if update.effective_chat.type in ["group", "supergroup"]:
        chat_id = update.effective_chat.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await update.message.reply_text(get_text(user_id, "admin_only"))
            return
        await db_set_chat_lock(chat_id, True, user_id)
        await update.message.reply_text(get_text(user_id, "locked"), parse_mode="MarkdownV2")
        return
    args = context.args
    if args and args[0].lstrip("-").isdigit():
        chat_id = int(args[0])
        if await is_authorized_in_group(context.bot, chat_id, user_id):
            await db_set_chat_lock(chat_id, True, user_id)
            await update.message.reply_text(get_text(user_id, "locked"), parse_mode="MarkdownV2")
            return
        else:
            await update.message.reply_text("❌ غير مصرح أو البوت ليس في المجموعة.")
            return
    groups = await db_get_user_groups(user_id)
    if not groups:
        await update.message.reply_text("📭 لا توجد مجموعات مسجلة.\nأضف البوت إلى مجموعة واجعلها نشطة.")
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        if await is_authorized_in_group(context.bot, gid, user_id):
            keyboard.append([InlineKeyboardButton(f"🔒 {gname[:30]}", callback_data=f"{CallbackData.PANEL_LOCK_PREFIX}{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    await update.message.reply_text("🔒 **اختر مجموعة لقفلها:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def unlock_chat_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat is None or update.effective_user is None:
        return
    user_id = update.effective_user.id
    chat_id = None
    if update.effective_chat.type in ["group", "supergroup"]:
        chat_id = update.effective_chat.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await update.message.reply_text(get_text(user_id, "admin_only"))
            return
        await db_set_chat_lock(chat_id, False)
        await update.message.reply_text(get_text(user_id, "unlocked"), parse_mode="MarkdownV2")
        return
    args = context.args
    if args and args[0].lstrip("-").isdigit():
        chat_id = int(args[0])
        if await is_authorized_in_group(context.bot, chat_id, user_id):
            await db_set_chat_lock(chat_id, False)
            await update.message.reply_text(get_text(user_id, "unlocked"), parse_mode="MarkdownV2")
            return
        else:
            await update.message.reply_text("❌ غير مصرح أو البوت ليس في المجموعة.")
            return
    groups = await db_get_user_groups(user_id)
    if not groups:
        await update.message.reply_text("📭 لا توجد مجموعات مسجلة.")
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        if await is_authorized_in_group(context.bot, gid, user_id):
            keyboard.append([InlineKeyboardButton(f"🔓 {gname[:30]}", callback_data=f"{CallbackData.PANEL_UNLOCK_PREFIX}{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    await update.message.reply_text("🔓 **اختر مجموعة لفتحها:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def panel_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.effective_user is None:
        return
    user_id = update.effective_user.id
    if not await ensure_force_subscribe(update, context, user_id):
        return
    if update.effective_chat.type in ["group", "supergroup"]:
        chat = update.effective_chat
        chat_id = chat.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await update.message.reply_text(get_text(user_id, "admin_only"))
            return
        current_lock_status = await is_chat_locked(chat_id)
        lock_status_text = "🔒 مقفلة" if current_lock_status else "🔓 مفتوحة"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔒 قفل المجموعة", callback_data=f"{CallbackData.PANEL_LOCK_PREFIX}{chat_id}"), InlineKeyboardButton("🔓 فتح المجموعة", callback_data=f"{CallbackData.PANEL_UNLOCK_PREFIX}{chat_id}")], [InlineKeyboardButton("🛠️ إجراءات متقدمة", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}"), InlineKeyboardButton("🔙 إغلاق اللوحة", callback_data=CallbackData.PANEL_CLOSE)]])
        await update.message.reply_text(f"🔧 **لوحة تحكم المجموعة**\n━━━━━━━━━━━━━━\n📌 **المجموعة:** {chat.title}\n🔐 **الحالة:** {lock_status_text}\n━━━━━━━━━━━━━━\n\nاستخدم الأزرار للتحكم في قفل وفتح المجموعة والإجراءات المتقدمة", reply_markup=kb, parse_mode="MarkdownV2")
        return
    groups = await db_get_user_groups(user_id)
    if not groups:
        await update.message.reply_text("📭 لا توجد مجموعات مسجلة.\nأضف البوت إلى مجموعة واجعلها نشطة.")
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        if await is_authorized_in_group(context.bot, gid, user_id):
            is_locked = await is_chat_locked(gid)
            icon = "🔒" if is_locked else "🔓"
            keyboard.append([InlineKeyboardButton(f"{icon} {gname[:30]}", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    await update.message.reply_text("🔧 **لوحة التحكم**\nاختر مجموعة:", reply_markup=InlineKeyboardMarkup(keyboard))

async def schedule_post_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.effective_user is None:
        return
    user_id = update.effective_user.id
    chat_id = None
    args = context.args
    if update.effective_chat.type in ["group", "supergroup"]:
        chat_id = update.effective_chat.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
            return
        if len(args) < 3:
            await update.message.reply_text("📝 **الاستخدام:**\n`/schedule YYYY-MM-DD HH:MM نص المنشور`", parse_mode="MarkdownV2")
            return
        try:
            date_str = args[0]
            time_str = args[1]
            text = " ".join(args[2:])
            mecca_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            if mecca_dt <= mecca_now():
                await update.message.reply_text("❌ **الوقت يجب أن يكون في المستقبل!**", parse_mode="MarkdownV2")
                return
            utc_dt = mecca_to_utc(mecca_dt)
            await db_add_scheduled_post(chat_id, text, utc_dt)
            await update.message.reply_text(f"✅ **تم جدولة المنشور!**\n📅 {date_str} 🕐 {time_str} (بتوقيت مكة)", parse_mode="MarkdownV2")
            return
        except ValueError:
            await update.message.reply_text("❌ صيغة التاريخ أو الوقت غير صحيحة!", parse_mode="MarkdownV2")
            return
    if len(args) >= 4:
        try:
            chat_id = int(args[0])
            date_str = args[1]
            time_str = args[2]
            text = " ".join(args[3:])
        except ValueError:
            await update.message.reply_text("❌ معرف المجموعة غير صحيح!")
            return
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await update.message.reply_text("❌ غير مصرح أو البوت ليس في المجموعة.")
            return
        try:
            mecca_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            if mecca_dt <= mecca_now():
                await update.message.reply_text("❌ **الوقت يجب أن يكون في المستقبل!**", parse_mode="MarkdownV2")
                return
            utc_dt = mecca_to_utc(mecca_dt)
            await db_add_scheduled_post(chat_id, text, utc_dt)
            await update.message.reply_text(f"✅ **تم جدولة المنشور!**\n📅 {date_str} 🕐 {time_str} (بتوقيت مكة)", parse_mode="MarkdownV2")
            return
        except ValueError:
            await update.message.reply_text("❌ صيغة التاريخ أو الوقت غير صحيحة!", parse_mode="MarkdownV2")
            return
    groups = await db_get_user_groups(user_id)
    if not groups:
        await update.message.reply_text("📭 لا توجد مجموعات مسجلة.")
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        if await is_authorized_in_group(context.bot, gid, user_id):
            keyboard.append([InlineKeyboardButton(f"📌 {gname[:30]}", callback_data=f"schedule_select:{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    await update.message.reply_text("📝 **اختر مجموعة لجدولة منشور:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def schedule_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split(":")[-1])
    context.user_data["schedule_chat_id"] = chat_id
    context.user_data["state"] = "WAITING_SCHEDULE_POST"
    await query.edit_message_text("📝 **أرسل المنشور بالصيغة التالية:**\n`YYYY-MM-DD HH:MM نص المنشور`\n\nمثال: `2024-12-31 20:00 مرحباً بالجميع!`\n🕐 الوقت بتوقيت مكة المكرمة", parse_mode="MarkdownV2")

async def set_log_channel_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text(get_text(user_id, "admin_only"))
        return
    args = context.args
    if not args and context.user_data.get("state") == "WAITING_LOG_CHANNEL":
        identifier = context.user_data.get("temp_log_channel_identifier")
        if identifier:
            args = [identifier]
    if not args:
        await update.message.reply_text("📝 **الاستخدام:**\n`/set_log_channel معرف_القناة`\n\nمثال: `/set_log_channel -1001234567890`\nأو `/set_log_channel @username`", parse_mode="MarkdownV2")
        return
    identifier = args[0].strip()
    if identifier.startswith("@"):
        identifier = identifier[1:]
    try:
        if identifier.startswith("-100") or identifier.lstrip("-").isdigit():
            chat_id = int(identifier)
        else:
            chat = await context.bot.get_chat(f"@{identifier}")
            chat_id = chat.id
    except Exception as e:
        await update.message.reply_text(f"❌ لا يمكن العثور على القناة: {e}", parse_mode="MarkdownV2")
        return
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        if bot_member.status not in ["administrator", "creator"]:
            await update.message.reply_text("❌ **البوت ليس مشرفاً في هذه القناة.**", parse_mode="MarkdownV2")
            return
        if not bot_member.can_post_messages:
            await update.message.reply_text("❌ **البوت لا يملك صلاحية الإرسال.**", parse_mode="MarkdownV2")
            return
    except Exception as e:
        await update.message.reply_text(f"❌ لا يمكن الوصول للقناة: {e}", parse_mode="MarkdownV2")
        return
    await db_set_log_channel_id(str(chat_id))
    await update.message.reply_text(f"✅ **تم تعيين قناة التقارير بنجاح!**\nمعرف القناة: `{chat_id}`", parse_mode="MarkdownV2")
    try:
        await context.bot.send_message(chat_id, "✅ **تم تفعيل نظام التقارير**")
    except:
        pass
    context.user_data.pop("state", None)
    context.user_data.pop("temp_log_channel_identifier", None)

async def handle_moderation_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        return
    user_id = update.effective_user.id
    chat_id = chat.id
    text = update.message.text.strip() if update.message.text else ""
    if not await check_admin_access(update, context):
        await update.message.reply_text(get_text(user_id, "admin_only"))
        return
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms["can_act"]:
        await update.message.reply_text(f"❌ {bot_perms['reason']}")
        return
    def extract_user_id_from_text(txt: str):
        parts = txt.split()
        if len(parts) >= 2:
            try:
                return int(parts[1])
            except ValueError:
                if parts[1].startswith("@"):
                    return parts[1]
        return None
    async def get_target_user_id(txt: str, reply_msg):
        if reply_msg and reply_msg.from_user:
            return reply_msg.from_user.id
        extracted = extract_user_id_from_text(txt)
        if extracted:
            if isinstance(extracted, int):
                return extracted
            if isinstance(extracted, str) and extracted.startswith("@"):
                try:
                    chat = await context.bot.get_chat(extracted)
                    return chat.id
                except:
                    return None
        return None
    reason = ""
    args = text.split(maxsplit=1)
    if len(args) > 1:
        parts = args[1].split(maxsplit=1)
        if len(parts) > 1:
            reason = parts[1]
    target_id = await get_target_user_id(text, update.message.reply_to_message)
    if not target_id:
        await update.message.reply_text("❌ يرجى تحديد المستخدم (ID أو @username) أو الرد على رسالته.")
        return
    if text.startswith("/ban"):
        success, msg = await execute_ban(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/mute"):
        minutes = context.user_data.get("mute_minutes", 60)
        success, msg = await execute_mute(context.bot, chat_id, target_id, minutes, reason=reason, moderator_id=user_id)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/unmute"):
        success, msg = await execute_unmute(context.bot, chat_id, target_id, moderator_id=user_id)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/warn"):
        success, msg = await execute_warn(context.bot, chat_id, target_id, user_id, reason=reason)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/kick"):
        success, msg = await execute_kick(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/restrict"):
        success, msg = await execute_restrict(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/pin") and update.message.reply_to_message:
        success, msg = await execute_pin(context.bot, chat_id, update.message.reply_to_message.message_id)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/unban"):
        success, msg = await execute_unban(context.bot, chat_id, target_id, moderator_id=user_id)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/add_banned_word"):
        args = text.split(maxsplit=1)
        if len(args) < 2:
            await update.message.reply_text("📝 **الاستخدام:** `/add_banned_word كلمة`")
            return
        word = args[1].strip().lower()
        if len(word) < 2:
            await update.message.reply_text("❌ الكلمة قصيرة جداً.")
            return
        if await db_add_banned_word(word, -1, user_id):
            await update.message.reply_text(f"✅ تم إضافة `{word}` ككلمة محظورة عامة.", parse_mode="MarkdownV2")
        else:
            await update.message.reply_text(f"⚠️ الكلمة `{word}` موجودة مسبقاً.", parse_mode="MarkdownV2")
        return
    if text.startswith("/remove_banned_word"):
        args = text.split(maxsplit=1)
        if len(args) < 2:
            await update.message.reply_text("📝 **الاستخدام:** `/remove_banned_word كلمة`")
            return
        word = args[1].strip().lower()
        async def _remove_global(conn):
            await conn.execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", (word, -1))
            await conn.commit()
        await execute_db(_remove_global)
        await update.message.reply_text(f"✅ تم حذف `{word}` من الكلمات المحظورة العامة.", parse_mode="MarkdownV2")
        return

async def message_handler_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    chat = update.effective_chat
    user = update.effective_user
    uid = user.id if user else 0
    text = update.message.text.strip() if update.message.text else ""
    if user and user.is_bot:
        return
    if update.message.photo:
        file = await context.bot.get_file(update.message.photo[-1].file_id)
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ حجم الصورة كبير جداً (الحد الأقصى {MAX_FILE_SIZE//(1024*1024)} ميجابايت)")
            return
    if update.message.video:
        file = await context.bot.get_file(update.message.video.file_id)
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ حجم الفيديو كبير جداً (الحد الأقصى {MAX_FILE_SIZE//(1024*1024)} ميجابايت)")
            return
    if update.message.document:
        file = await context.bot.get_file(update.message.document.file_id)
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ حجم الملف كبير جداً (الحد الأقصى {MAX_FILE_SIZE//(1024*1024)} ميجابايت)")
            return
    if update.message.audio:
        file = await context.bot.get_file(update.message.audio.file_id)
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ حجم الصوت كبير جداً (الحد الأقصى {MAX_FILE_SIZE//(1024*1024)} ميجابايت)")
            return
    if update.message.voice:
        file = await context.bot.get_file(update.message.voice.file_id)
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ حجم الرسالة الصوتية كبير جداً (الحد الأقصى {MAX_FILE_SIZE//(1024*1024)} ميجابايت)")
            return
    if update.message.animation:
        file = await context.bot.get_file(update.message.animation.file_id)
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ حجم المتحركة كبير جداً (الحد الأقصى {MAX_FILE_SIZE//(1024*1024)} ميجابايت)")
            return
    if text == "/cancel":
        context.user_data.pop("state", None)
        context.user_data.pop("support_mode", None)
        await update.message.reply_text(get_text(uid, "cancelled"))
        if chat.type == "private":
            await main_menu_callback(update, context)
        return
    if context.user_data.get("waiting_2fa") and text:
        if ENABLE_2FA and ADMIN_2FA_SECRET and PYOTP_AVAILABLE:
            try:
                totp = pyotp.TOTP(ADMIN_2FA_SECRET)
                if totp.verify(text):
                    context.user_data["2fa_verified"] = True
                    context.user_data["2fa_time"] = time.time()
                    context.user_data.pop("waiting_2fa", None)
                    await update.message.reply_text("✅ تم التحقق من المصادقة الثنائية!")
                    await sendcode_command_handler(update, context)
                    return
                else:
                    await update.message.reply_text("❌ رمز غير صحيح!")
                    context.user_data.pop("waiting_2fa", None)
                    return
            except:
                await update.message.reply_text("❌ خطأ في التحقق")
                context.user_data.pop("waiting_2fa", None)
                return
    state = context.user_data.get("state")
    if state == "ADDING_POSTS":
        session_key = f"session_{uid}"
        if text == "/cancel":
            context.user_data.pop(session_key, None)
            context.user_data.pop(f"session_target_{uid}", None)
            context.user_data.pop("state", None)
            await update.message.reply_text(get_text(uid, "cancelled"))
            await main_menu_callback(update, context)
            return
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
        elif update.message.audio:
            media_type = "audio"
            media_file_id = update.message.audio.file_id
            text_content = update.message.caption or ""
        elif update.message.voice:
            media_type = "voice"
            media_file_id = update.message.voice.file_id
            text_content = update.message.caption or ""
        elif update.message.animation:
            media_type = "animation"
            media_file_id = update.message.animation.file_id
            text_content = update.message.caption or ""
        context.user_data[session_key].append((text_content, media_type, media_file_id))
        cur = len(context.user_data[session_key])
        target = context.user_data.get(f"session_target_{uid}", 15)
        if cur >= target or cur >= MAX_POSTS_PER_SESSION:
            active = context.user_data.get("active_channel") or await db_get_active_channel(uid)
            if not active:
                await update.message.reply_text(get_text(uid, "error"))
                context.user_data.pop(session_key, None)
                context.user_data.pop("state", None)
                return
            saved = await db_save_posts(active, context.user_data[session_key])
            context.user_data.pop(session_key, None)
            context.user_data.pop(f"session_target_{uid}", None)
            context.user_data.pop("state", None)
            has_sub = await db_has_active_subscription(uid) or await db_has_used_trial(uid)
            auto_status = await db_auto_status(uid)
            if not has_sub:
                await update.message.reply_text(f"✅ تم حفظ {saved} منشور\n⚠️ النشر التلقائي غير مفعل بسبب عدم وجود اشتراك\nاستخدم /trial للحصول على 30 يوماً مجاناً")
            elif not auto_status:
                await update.message.reply_text(f"✅ تم حفظ {saved} منشور\n⚠️ النشر التلقائي معطل\nفعله من الإعدادات")
            else:
                await update.message.reply_text(f"✅ تم حفظ {saved} منشور\n🔄 سيتم نشرها تلقائياً")
            await main_menu_callback(update, context)
        else:
            await update.message.reply_text(f"📥 {cur}/{target}")
        return
    if state in ["WAITING_CONTEST_TITLE", "WAITING_CONTEST_DESCRIPTION", "WAITING_CONTEST_PRIZE", "WAITING_CONTEST_END_DATE", "WAITING_CONTEST_ANSWER"]:
        if await handle_contest_creation_states(update, context, state):
            return
    if state == "WAITING_SENDCODE_PASSWORD":
        await handle_sendcode_confirmation_handler(update, context)
        return
    if state == "WAITING_CHANNEL_ID":
        context.user_data.pop("state", None)
        channel_id = text.strip()
        if not channel_id.startswith("@") and not channel_id.startswith("-100"):
            await update.message.reply_text("❌ **معرف قناة غير صالح!**\n\nالصيغ المدعومة:\n• `@username` (مثل: @my_channel)\n• `-1001234567890` (المعرف الرقمي)\n\nتأكد من أن البوت مشرف في القناة.", parse_mode="MarkdownV2")
            context.user_data["state"] = "WAITING_CHANNEL_ID"
            return
        new_id = await db_add_channel(uid, channel_id, channel_id)
        if new_id:
            context.user_data["active_channel"] = new_id
            await db_set_active_channel(uid, new_id)
            await update.message.reply_text(get_text(uid, "channel_added").format(channel_id))
        else:
            await update.message.reply_text(get_text(uid, "channel_exists"))
        await main_menu_callback(update, context)
        return
    if state == "WAITING_INTERVAL_MINUTES":
        context.user_data.pop("state", None)
        ch_db_id = context.user_data.pop("schedule_ch_id", None)
        is_admin = context.user_data.pop("admin_interval", False)
        is_cron = context.user_data.pop("schedule_cron", False)
        if is_cron:
            cron_expr = text.strip()
            if len(cron_expr.split()) >= 5:
                await schedule_cron(ch_db_id, cron_expr)
                await db_set_next_publish_date(ch_db_id, None)
                await update.message.reply_text(f"✅ **تم حفظ تعبير CRON:** `{cron_expr}`")
                await schedule_menu_callback(update, context)
                return
            else:
                await update.message.reply_text("❌ **تعبير CRON غير صحيح!**\nتأكد من الصيغة: `دقيقة ساعة يوم شهر يوم_أسبوع`")
                return
        try:
            minutes = int(text)
            if minutes < 1:
                minutes = 1
            if is_admin:
                seconds = minutes * 60
                if seconds > 86400:
                    seconds = 86400
                await db_set_publish_interval_seconds(seconds, uid, is_admin=True)
                await update.message.reply_text(f"✅ **تم ضبط وقت النشر العام بنجاح!**\n\n🕐 الوقت الجديد: {minutes} دقيقة ({seconds} ثانية)")
                await admin_panel_callback(update, context)
            else:
                await db_save_schedule(ch_db_id, "interval_minutes", interval_minutes=minutes)
                await db_set_next_publish_date(ch_db_id, None)
                await update.message.reply_text(get_text(uid, "interval_set"))
                await schedule_menu_callback(update, context)
        except ValueError:
            await update.message.reply_text(get_text(uid, "invalid_number"))
        return
    if state == "WAITING_INTERVAL_HOURS":
        context.user_data.pop("state", None)
        ch_db_id = context.user_data.pop("schedule_ch_id", None)
        try:
            hours = int(text)
            if hours < 1:
                hours = 1
            await db_save_schedule(ch_db_id, "interval_hours", interval_hours=hours)
            await db_set_next_publish_date(ch_db_id, None)
            await update.message.reply_text(get_text(uid, "interval_set"))
        except:
            await update.message.reply_text(get_text(uid, "invalid_number"))
        await schedule_menu_callback(update, context)
        return
    if state == "WAITING_INTERVAL_DAYS":
        context.user_data.pop("state", None)
        ch_db_id = context.user_data.pop("schedule_ch_id", None)
        try:
            days = int(text)
            if days < 1:
                days = 1
            await db_save_schedule(ch_db_id, "interval_days", interval_days=days)
            await db_set_next_publish_date(ch_db_id, None)
            await update.message.reply_text(get_text(uid, "interval_set"))
        except:
            await update.message.reply_text(get_text(uid, "invalid_number"))
        await schedule_menu_callback(update, context)
        return
    if state == "WAITING_DATES":
        context.user_data.pop("state", None)
        ch_db_id = context.user_data.pop("schedule_ch_id", None)
        dates = text.split(",")
        valid_dates = []
        for d in dates:
            d = d.strip()
            try:
                datetime.strptime(d, "%Y-%m-%d")
                valid_dates.append(d)
            except:
                await update.message.reply_text(get_text(uid, "invalid_date"))
                return
        await db_save_schedule(ch_db_id, "dates", specific_dates=json.dumps(valid_dates))
        await db_set_next_publish_date(ch_db_id, None)
        await update.message.reply_text(get_text(uid, "dates_saved"))
        await schedule_menu_callback(update, context)
        return
    if state == "WAITING_PUBLISH_TIME":
        context.user_data.pop("state", None)
        ch_db_id = context.user_data.pop("schedule_ch_id", None)
        try:
            time_str = text.strip()
            hour, minute = map(int, time_str.split(":"))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                await db_set_publish_time(ch_db_id, time_str)
                await db_set_next_publish_date(ch_db_id, None)
                await update.message.reply_text(get_text(uid, "interval_set"))
            else:
                await update.message.reply_text(get_text(uid, "invalid_time"))
        except:
            await update.message.reply_text(get_text(uid, "invalid_time"))
        await schedule_menu_callback(update, context)
        return
    if state == "WAITING_SCHEDULE_POST":
        context.user_data.pop("state", None)
        chat_id = context.user_data.get("schedule_chat_id")
        if not chat_id:
            await update.message.reply_text("❌ لم يتم تحديد المجموعة.")
            return
        args = text.split()
        if len(args) < 3:
            await update.message.reply_text("❌ **صيغة غير صحيحة!**\n\nالاستخدام الصحيح:\n`YYYY-MM-DD HH:MM نص المنشور`\n\nمثال: `2024-12-31 20:00 مرحباً بالجميع!`", parse_mode="MarkdownV2")
            return
        try:
            date_str = args[0]
            time_str = args[1]
            post_text = " ".join(args[2:])
            mecca_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            if mecca_dt <= mecca_now():
                await update.message.reply_text("❌ **الوقت يجب أن يكون في المستقبل!**", parse_mode="MarkdownV2")
                return
            utc_dt = mecca_to_utc(mecca_dt)
            await db_add_scheduled_post(chat_id, post_text, utc_dt)
            await update.message.reply_text(f"✅ **تم جدولة المنشور بنجاح!**\n\n📅 التاريخ: {date_str}\n🕐 الوقت: {time_str} (بتوقيت مكة)\n📝 المنشور: {post_text[:100]}{'...' if len(post_text) > 100 else ''}", parse_mode="MarkdownV2")
        except ValueError:
            await update.message.reply_text("❌ **صيغة التاريخ أو الوقت غير صحيحة!**\n\nتأكد من الصيغة:\n• التاريخ: YYYY-MM-DD (مثال: 2024-12-31)\n• الوقت: HH:MM (مثال: 20:00)", parse_mode="MarkdownV2")
        await main_menu_callback(update, context)
        return
    if state == "WAITING_REMINDER_DAYS":
        context.user_data.pop("state", None)
        try:
            days = int(text)
            if 1 <= days <= 10:
                await db_update_reminder_settings(uid, reminder_days_before=days)
                await update.message.reply_text(f"✅ تم تعيين التذكير قبل {days} يوم من انتهاء الاشتراك")
            else:
                await update.message.reply_text("❌ الرجاء إدخال رقم بين 1 و 10")
        except ValueError:
            await update.message.reply_text("❌ الرجاء إدخال رقم صحيح")
        await reminder_menu_callback(update, context)
        return
    if state == "WAITING_UPDATE_TEXT":
        context.user_data.pop("state", None)
        channel = await db_get_updates_channel()
        if channel:
            try:
                await context.bot.send_message(chat_id=f"@{channel}", text=text, parse_mode="HTML")
                await update.message.reply_text("✅ تم نشر التحديث في قناة التحديثات")
            except Exception as e:
                await update.message.reply_text(f"❌ فشل النشر: {str(e)[:100]}\nتأكد من أن البوت مشرف في القناة @{channel}")
        else:
            await update.message.reply_text("❌ لم يتم تعيين قناة تحديثات بعد\nاستخدم زر '⚙️ قناة التحديثات' أولاً")
        await admin_panel_callback(update, context)
        return
    if state == "WAITING_UPDATE_CHANNEL":
        context.user_data.pop("state", None)
        channel = text.strip()
        if channel.startswith("@"):
            channel = channel[1:]
        if not channel:
            await update.message.reply_text("❌ **معرف قناة غير صالح!**\nالرجاء إدخال معرف صحيح.")
            return
        try:
            if channel.startswith("-"):
                chat_obj = await context.bot.get_chat(int(channel))
            else:
                chat_obj = await context.bot.get_chat(f"@{channel}")
            if chat_obj.type != "channel":
                await update.message.reply_text("❌ **هذا ليس قناة!**\nتأكد من أن المعرف ينتمي لقناة.")
                return
            success = await db_set_updates_channel(channel)
            if success:
                saved_channel = await db_get_updates_channel()
                if saved_channel == channel:
                    await update.message.reply_text(f"✅ **تم تعيين قناة التحديثات بنجاح!**\n📢 القناة: @{channel}")
                    try:
                        await context.bot.send_message(chat_id=f"@{channel}", text="✅ **تم تفعيل قناة التحديثات!**\nسيتم نشر التحديثات هنا.")
                        await update.message.reply_text("✅ تم إرسال رسالة اختبار للقناة.")
                    except Exception as e:
                        await update.message.reply_text(f"⚠️ **تنبيه:** لم أتمكن من إرسال رسالة اختبار للقناة.\nتأكد من أن البوت مشرف ولديه صلاحية الإرسال.\nالخطأ: {str(e)[:100]}")
                else:
                    await update.message.reply_text("❌ **فشل حفظ القناة!** حاول مرة أخرى.")
            else:
                await update.message.reply_text("❌ **فشل حفظ القناة!** المعرف غير صالح.")
        except Exception as e:
            await update.message.reply_text(f"❌ **لا يمكن الوصول إلى القناة:**\n{str(e)[:200]}\n\n📌 تأكد من:\n• المعرف صحيح\n• البوت مشرف في القناة\n• القناة عامة (Public)")
        await admin_panel_callback(update, context)
        return
    if state == "WAITING_FORCE_CHANNEL":
        context.user_data.pop("state", None)
        await db_set_force_subscribe_channel(text)
        await update.message.reply_text(f"✅ تم تعيين قناة الاشتراك الإجباري: {text}")
        await admin_panel_callback(update, context)
        return
    if state == "WAITING_BROADCAST":
        context.user_data.pop("state", None)
        confirm_kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ نعم، أرسل", callback_data=CallbackData.ADMIN_CONFIRM_BROADCAST), InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.ADMIN_PANEL)]])
        context.user_data["broadcast_text"] = text
        await update.message.reply_text(f"📨 **تأكيد الإرسال الجماعي**\n\nالنص المرسل:\n━━━━━━━━━━━━━━\n{text[:500]}\n━━━━━━━━━━━━━━\n\n⚠️ سيتم إرسال هذه الرسالة إلى **جميع مستخدمي البوت**\nهل أنت متأكد؟", reply_markup=confirm_kb, parse_mode="MarkdownV2")
        return
    if state == "WAITING_SENDCODE_USER":
        context.user_data.pop("state", None)
        try:
            target_user_id = int(text)
        except ValueError:
            await update.message.reply_text(get_text(uid, "invalid_number"))
            return
        await db_set_allowed_sendcode_user(target_user_id)
        await security_audit.log("SENDCODE_PERMISSION_GRANTED", uid, {"target": target_user_id}, "CRITICAL")
        await update.message.reply_text(get_text(uid, "sendcode_user_set").format(target_user_id), parse_mode="MarkdownV2")
        await admin_panel_callback(update, context)
        return
    if state == "WAITING_LOG_CHANNEL":
        context.user_data.pop("state", None)
        identifier = text.strip()
        if not identifier.startswith("@") and not identifier.startswith("-100"):
            await update.message.reply_text("❌ **معرف قناة غير صالح!**\n\nالصيغ المدعومة:\n• `@username` (مثل: @my_channel)\n• `-1001234567890` (المعرف الرقمي)", parse_mode="MarkdownV2")
            context.user_data["state"] = "WAITING_LOG_CHANNEL"
            return
        try:
            identifier_clean = identifier.lstrip("@")
            if identifier_clean.startswith("-100") or identifier_clean.lstrip("-").isdigit():
                chat_id = int(identifier_clean)
            else:
                chat_obj = await context.bot.get_chat(f"@{identifier_clean}")
                chat_id = chat_obj.id
            bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
            if bot_member.status not in ["administrator", "creator"]:
                await update.message.reply_text("❌ **البوت ليس مشرفاً في هذه القناة.**", parse_mode="MarkdownV2")
                context.user_data["state"] = "WAITING_LOG_CHANNEL"
                return
            if not bot_member.can_post_messages:
                await update.message.reply_text("❌ **البوت لا يملك صلاحية الإرسال في هذه القناة.**", parse_mode="MarkdownV2")
                context.user_data["state"] = "WAITING_LOG_CHANNEL"
                return
            await db_set_log_channel_id(str(chat_id))
            await update.message.reply_text(f"✅ **تم تعيين قناة التقارير بنجاح!**\nمعرف القناة: `{chat_id}`", parse_mode="MarkdownV2")
            try:
                await context.bot.send_message(chat_id, "✅ **تم تفعيل نظام التقارير**")
            except:
                pass
        except Exception as e:
            await update.message.reply_text(f"❌ **لا يمكن الوصول إلى القناة:**\n{str(e)[:200]}", parse_mode="MarkdownV2")
            context.user_data["state"] = "WAITING_LOG_CHANNEL"
            return
        await admin_panel_callback(update, context)
        return
    if state == "WAITING_KEYWORD":
        context.user_data.pop("state", None)
        keyword = text.strip().lower()
        if len(keyword) < 2:
            await update.message.reply_text("❌ الكلمة المفتاحية قصيرة جداً (يجب أن تكون حرفين على الأقل)")
            context.user_data["state"] = "WAITING_KEYWORD"
            return
        context.user_data["state"] = "WAITING_REPLY"
        context.user_data["admin_keyword"] = keyword
        await update.message.reply_text(f"📝 **إضافة رد للكلمة:** `{keyword}`\n\nأرسل الرد الذي تريده لهذه الكلمة:", parse_mode="MarkdownV2")
        return
    if state == "WAITING_REPLY":
        context.user_data.pop("state", None)
        if context.user_data.get("admin_del_reply"):
            kw = text.lower()
            if await db_del_reply(kw):
                await update.message.reply_text(f"✅ تم حذف رد {kw}")
            else:
                await update.message.reply_text(f"⚠️ الكلمة {kw} غير موجودة")
            context.user_data.pop("admin_del_reply", None)
            await admin_replies_callback(update, context)
            return
        kw = context.user_data.pop("admin_keyword", "")
        reply = text.strip()
        if kw and reply:
            await db_add_reply(kw, reply)
            await update.message.reply_text(f"✅ تم إضافة رد للكلمة {kw}")
        else:
            await update.message.reply_text("❌ حدث خطأ")
        await admin_replies_callback(update, context)
        return
    if state == "WAITING_ADMIN_ID_ADD":
        try:
            target_id = int(text)
            if target_id == PRIMARY_OWNER_ID:
                await update.message.reply_text(get_text(uid, "cannot_remove_main_admin"))
            else:
                await add_bot_admin(target_id)
                await security_audit.log("ADMIN_ADDED", uid, {"target": target_id}, "CRITICAL")
                await update.message.reply_text(get_text(uid, "add_admin_success").format(target_id), parse_mode="MarkdownV2")
        except ValueError:
            await update.message.reply_text(get_text(uid, "invalid_user_id"))
        context.user_data.pop("state", None)
        await admin_panel_callback(update, context)
        return
    if state == "WAITING_ADMIN_ID_REMOVE":
        try:
            target_id = int(text)
            if target_id == PRIMARY_OWNER_ID:
                await update.message.reply_text(get_text(uid, "cannot_remove_main_admin"))
            else:
                await remove_bot_admin(target_id)
                await security_audit.log("ADMIN_REMOVED", uid, {"target": target_id}, "CRITICAL")
                await update.message.reply_text(get_text(uid, "remove_admin_success").format(target_id), parse_mode="MarkdownV2")
        except ValueError:
            await update.message.reply_text(get_text(uid, "invalid_user_id"))
        context.user_data.pop("state", None)
        await admin_panel_callback(update, context)
        return
    if state == "WAITING_GROUP_BANNED_WORD":
        chat_id = context.user_data.get("banned_words_chat_id")
        if chat_id:
            word = text.split()[0].lower() if text else ""
            if len(word) < 2:
                await update.message.reply_text("❌ الكلمة قصيرة جداً")
                return
            if await db_add_banned_word(word, chat_id, uid):
                await update.message.reply_text(f"✅ تم إضافة {word}")
            else:
                await update.message.reply_text(f"⚠️ {word} موجودة مسبقاً")
            context.user_data.pop("state", None)
            await banned_words_list_callback(update, context)
        return
    if state == "WAITING_REMOVE_GROUP_BANNED_WORD":
        chat_id = context.user_data.get("banned_words_chat_id")
        if chat_id:
            word = text.lower()
            if await db_remove_banned_word(word, chat_id):
                await update.message.reply_text(f"✅ تم حذف {word}")
            else:
                await update.message.reply_text(f"⚠️ الكلمة {word} غير موجودة")
            context.user_data.pop("state", None)
            await banned_words_list_callback(update, context)
        return
    if state == "WAITING_GLOBAL_BANNED_WORD":
        word = text.split()[0].lower() if text else ""
        if len(word) < 2:
            await update.message.reply_text("❌ الكلمة قصيرة جداً")
            return
        if await db_add_banned_word(word, -1, uid):
            await update.message.reply_text(f"✅ تم إضافة {word} ككلمة محظورة عامة")
        else:
            await update.message.reply_text(f"⚠️ {word} موجودة مسبقاً")
        context.user_data.pop("state", None)
        await admin_banned_words_callback(update, context)
        return
    if state == "WAITING_REMOVE_GLOBAL_BANNED_WORD":
        word = text.lower()
        async def _remove(conn):
            await conn.execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", (word, -1))
            await conn.commit()
        await execute_db(_remove)
        await update.message.reply_text(f"✅ تم حذف {word} من الكلمات المحظورة العامة")
        context.user_data.pop("state", None)
        await admin_banned_words_callback(update, context)
        return
    if state == "WAITING_NSFW_THRESHOLD":
        try:
            threshold = float(text)
            if 0 < threshold <= 100:
                global NSFW_THRESHOLD
                NSFW_THRESHOLD = threshold / 100
                os.environ["NSFW_THRESHOLD"] = str(NSFW_THRESHOLD)
                await update.message.reply_text(f"✅ تم تغيير نسبة الحساسية إلى: {threshold}%")
            else:
                await update.message.reply_text("❌ الرجاء إدخال رقم بين 1 و 100")
        except ValueError:
            await update.message.reply_text("❌ الرجاء إدخال رقم صحيح (مثال: 75)")
        context.user_data.pop("state", None)
        await nsfw_settings_callback(update, context)
        return
    if state and state.startswith("WAITING_"):
        chat_id = context.user_data.get("advanced_chat_id")
        if not chat_id:
            return
        if state == "WAITING_BAN_USER":
            parts = text.split(maxsplit=1)
            reason = parts[1] if len(parts) > 1 else ""
            try:
                target_id = int(parts[0])
                success, msg = await execute_ban(context.bot, chat_id, target_id, reason=reason, moderator_id=uid)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
            context.user_data.pop("state", None)
            return
        if state == "WAITING_MUTE_USER":
            parts = text.split(maxsplit=1)
            reason = parts[1] if len(parts) > 1 else ""
            try:
                target_id = int(parts[0])
                minutes = context.user_data.get("mute_minutes", 60)
                success, msg = await execute_mute(context.bot, chat_id, target_id, minutes, reason=reason, moderator_id=uid)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
            context.user_data.pop("state", None)
            return
        if state == "WAITING_WARN_USER":
            parts = text.split(maxsplit=1)
            reason = parts[1] if len(parts) > 1 else ""
            try:
                target_id = int(parts[0])
                success, msg = await execute_warn(context.bot, chat_id, target_id, uid, reason=reason)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
            context.user_data.pop("state", None)
            return
        if state == "WAITING_KICK_USER":
            parts = text.split(maxsplit=1)
            reason = parts[1] if len(parts) > 1 else ""
            try:
                target_id = int(parts[0])
                success, msg = await execute_kick(context.bot, chat_id, target_id, reason=reason, moderator_id=uid)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
            context.user_data.pop("state", None)
            return
        if state == "WAITING_RESTRICT_USER":
            parts = text.split(maxsplit=1)
            reason = parts[1] if len(parts) > 1 else ""
            try:
                target_id = int(parts[0])
                success, msg = await execute_restrict(context.bot, chat_id, target_id, reason=reason, moderator_id=uid)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
            context.user_data.pop("state", None)
            return
        if state == "WAITING_UNBAN_USER":
            try:
                target_id = int(text)
                success, msg = await execute_unban(context.bot, chat_id, target_id, moderator_id=uid)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
            context.user_data.pop("state", None)
            return
        if state == "WAITING_PIN_MESSAGE":
            if update.message.reply_to_message:
                success, msg = await execute_pin(context.bot, chat_id, update.message.reply_to_message.message_id)
                await safe_send_markdown(context.bot, chat_id, msg)
            else:
                await update.message.reply_text("❌ يرجى الرد على الرسالة التي تريد تثبيتها")
            context.user_data.pop("state", None)
            return
    if context.user_data.get("support_mode") and chat.type == "private" and text and not text.startswith("/"):
        ticket_num = await db_get_next_ticket_number()
        username = user.full_name or user.first_name or str(uid)
        clean_text = sanitize_text(text, max_length=2000)
        await db_save_ticket(uid, username, clean_text, ticket_num)
        now_mecca = mecca_now()
        now_str = now_mecca.strftime("%Y-%m-%d %H:%M:%S")
        reply_text = f"✅ **تم استلام رسالتك!**\n📋 رقم التذكرة: #{ticket_num}\n🕐 {now_str}\n\nسيتم الرد عليك في أقرب وقت ممكن."
        await update.message.reply_text(reply_text, parse_mode="MarkdownV2")
        notification_text = f"📬 **تذكرة دعم جديدة**\n━━━━━━━━━━━━━━━━━━━━━━\n👤 المستخدم: {username}\n🆔 المعرف: `{uid}`\n📋 رقم التذكرة: #{ticket_num}\n🕐 الوقت: {now_str}\n━━━━━━━━━━━━━━━━━━━━━━\n📝 **الرسالة:**\n{clean_text[:500]}\n━━━━━━━━━━━━━━━━━━━━━━\nللرد استخدم:\n`/support_reply {uid} نص الرد`"
        await context.bot.send_message(chat_id=PRIMARY_OWNER_ID, text=notification_text, parse_mode="MarkdownV2")
        context.user_data["support_mode"] = False
        return
    if chat.type == "private":
        if text == "/start":
            await start_command_handler(update, context)
        elif text == "/cancel":
            context.user_data.pop("state", None)
            await update.message.reply_text(get_text(uid, "cancelled"))
            await main_menu_callback(update, context)

async def handle_contest_creation_states(update: Update, context: ContextTypes.DEFAULT_TYPE, state: str) -> bool:
    try:
        user_id = update.effective_user.id
        text = update.message.text.strip() if update.message.text else ""
        if state == "WAITING_CONTEST_TITLE":
            if not text:
                await update.message.reply_text("❌ الرجاء إدخال عنوان صحيح.")
                return True
            context.user_data["contest_title"] = text
            context.user_data["state"] = "WAITING_CONTEST_DESCRIPTION"
            await update.message.reply_text(get_text(user_id, "create_contest_description"))
            return True
        elif state == "WAITING_CONTEST_DESCRIPTION":
            if not text:
                await update.message.reply_text("❌ الرجاء إدخال وصف صحيح.")
                return True
            context.user_data["contest_description"] = text
            context.user_data["state"] = "WAITING_CONTEST_PRIZE"
            await update.message.reply_text(get_text(user_id, "create_contest_prize"))
            return True
        elif state == "WAITING_CONTEST_PRIZE":
            if not text:
                await update.message.reply_text("❌ الرجاء إدخال جائزة صحيحة.")
                return True
            context.user_data["contest_prize"] = text
            context.user_data["state"] = "WAITING_CONTEST_END_DATE"
            await update.message.reply_text(get_text(user_id, "create_contest_end_date"))
            return True
        elif state == "WAITING_CONTEST_END_DATE":
            try:
                end_date = datetime.strptime(text, "%Y-%m-%d %H:%M")
                now_mecca = mecca_now()
                if end_date <= now_mecca:
                    await update.message.reply_text(get_text(user_id, "contest_date_future"))
                    return True
                end_date_utc = mecca_to_utc(end_date)
                title = context.user_data.pop("contest_title", "بدون عنوان")
                description = context.user_data.pop("contest_description", "")
                prize = context.user_data.pop("contest_prize", "")
                contest_type = context.user_data.pop("contest_type", "raffle")
                contest_id = await db_create_contest(user_id, title, description, prize, end_date_utc, contest_type)
                if contest_id:
                    await update.message.reply_text(get_text(user_id, "contest_created").format(title, prize, end_date.strftime("%Y-%m-%d %H:%M"), contest_id))
                    try:
                        await context.bot.send_message(PRIMARY_OWNER_ID, get_text(PRIMARY_OWNER_ID, "contest_creator").format(user_id, title))
                    except:
                        pass
                else:
                    await update.message.reply_text(get_text(user_id, "contest_created_error"))
            except ValueError:
                await update.message.reply_text(get_text(user_id, "contest_date_invalid"))
                return True
            except Exception as e:
                error_id = log_error(e, {"user_id": user_id, "action": "create_contest", "date_input": text})
                await update.message.reply_text(f"❌ حدث خطأ أثناء إنشاء المسابقة (الرمز: `{error_id}`).\nيرجى المحاولة مرة أخرى أو إبلاغ المطور.")
                return True
            context.user_data.pop("state", None)
            await main_menu_callback(update, context)
            return True
        elif state == "WAITING_CONTEST_ANSWER":
            contest_id = context.user_data.get("contest_join_id")
            if not contest_id:
                await update.message.reply_text("❌ لم يتم العثور على المسابقة.")
                context.user_data.pop("state", None)
                return True
            answer = text if text else ""
            if answer.lower() == "/skip":
                answer = ""
            success = await db_participate_in_contest(user_id, contest_id, answer)
            if success:
                await update.message.reply_text(get_text(user_id, "contest_join_success"))
                try:
                    level_data = await db_get_user_level(user_id)
                    await db_update_user_level(user_id, level_data["points"] + 5, level_data["level"])
                except:
                    pass
            else:
                await update.message.reply_text(get_text(user_id, "contest_join_error"))
            context.user_data.pop("contest_join_id", None)
            context.user_data.pop("state", None)
            await contests_command_handler(update, context)
            return True
        return False
    except Exception as e:
        error_id = log_error(e, {"user_id": user_id, "state": state})
        await update.message.reply_text(f"❌ حدث خطأ غير متوقع أثناء إنشاء المسابقة (الرمز: `{error_id}`).\nيرجى المحاولة مرة أخرى لاحقاً.")
        context.user_data.pop("state", None)
        return True

async def sendcode_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    allowed_user = await db_get_allowed_sendcode_user()
    if user_id != PRIMARY_OWNER_ID and user_id != allowed_user:
        await safe_send_markdown(context.bot, user_id, "🔒 هذا الأمر للمطور الأساسي أو المستخدمين المصرح لهم فقط.")
        logger.warning(f"⚠️ Unauthorized /sendcode attempt from user: {user_id}")
        await security_audit.log("UNAUTHORIZED_SENDCODE_ATTEMPT", user_id, {}, "CRITICAL")
        return
    if ENABLE_2FA and ADMIN_2FA_SECRET and PYOTP_AVAILABLE:
        if not context.user_data.get("2fa_verified") or time.time() - context.user_data.get("2fa_time", 0) > 300:
            secret = ADMIN_2FA_SECRET
            totp = pyotp.TOTP(secret)
            context.user_data["waiting_2fa"] = True
            await update.message.reply_text("🔐 أدخل رمز المصادقة الثنائية (2FA):")
            return
    temp_password = secrets.token_urlsafe(12)
    context.user_data["sendcode_temp_password"] = temp_password
    context.user_data["sendcode_temp_timestamp"] = time.time()
    context.user_data["state"] = "WAITING_SENDCODE_PASSWORD"
    await update.message.reply_text(f"🔐 **تأكيد أمني إضافي**\n\nلإرسال الكود، يرجى تأكيد هويتك بإرسال كلمة المرور المؤقتة:\n`{temp_password}`\n\n⏰ **تنتهي الصلاحية خلال 10 دقائق.**")

async def handle_sendcode_confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    expected_password = context.user_data.get("sendcode_temp_password")
    timestamp = context.user_data.get("sendcode_temp_timestamp", 0)
    if not expected_password:
        await update.message.reply_text("❌ لم يتم طلب إرسال كود")
        context.user_data.pop("state", None)
        return
    SENDCODE_TIMEOUT = 600
    if time.time() - timestamp > SENDCODE_TIMEOUT:
        await update.message.reply_text(f"❌ انتهت صلاحية كلمة المرور (المهلة {SENDCODE_TIMEOUT // 60} دقائق).\nأعد استخدام الأمر /sendcode.")
        context.user_data.pop("sendcode_temp_password", None)
        context.user_data.pop("sendcode_temp_timestamp", None)
        context.user_data.pop("state", None)
        return
    if update.message.text.strip() == expected_password:
        try:
            with open(__file__, "r", encoding="utf-8") as f:
                content = f.read()
            watermark = f"""# ============================================================
# ORIGINAL_OWNER: {user_id}
# GENERATED_AT: {mecca_now().strftime('%Y-%m-%d %H:%M:%S')}
# SIGNATURE: {hashlib.sha256(f"{user_id}{time.time()}{TOKEN}".encode()).hexdigest()[:16]}
# ============================================================
# ⚠️ تحذير: هذا الكود يحتوي على معلومات حساسة
# لا تشاركه مع أي شخص غير موثوق
# ============================================================

"""
            watermarked_content = watermark + content
            temp_dir = tempfile.gettempdir()
            temp_file = os.path.join(temp_dir, f"bot_code_{user_id}_{int(time.time())}.py")
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(watermarked_content)
            with open(temp_file, "rb") as f:
                await context.bot.send_document(chat_id=user_id, document=f, filename=f"relax_bot_secure_{mecca_now().strftime('%Y%m%d')}.py", caption="⚠️ **هذا الكود موقع رقمياً - لا تشاركه مع أي شخص غير موثوق!**\n\n📌 يحتوي على:\n• التوكن والمفاتيح\n• هيكل قاعدة البيانات\n• معلومات حساسة أخرى")
            os.unlink(temp_file)
            await security_audit.log("SENDCODE_EXECUTED", user_id, {"timestamp": mecca_now_iso()}, "CRITICAL")
            await update.message.reply_text("✅ تم إرسال الكود بنجاح على الخاص!")
            logger.info(f"📁 Sent bot code to user {user_id} in private")
        except Exception as e:
            await update.message.reply_text(f"❌ فشل إرسال الكود: {str(e)[:100]}")
            logger.error(f"Error sending code: {e}")
        context.user_data.pop("sendcode_temp_password", None)
        context.user_data.pop("sendcode_temp_timestamp", None)
        context.user_data.pop("state", None)
    else:
        await update.message.reply_text("❌ كلمة المرور غير صحيحة! تم إلغاء العملية.")
        await security_audit.log("SENDCODE_FAILED_ATTEMPT", user_id, {"attempt": update.message.text[:6]}, "HIGH")
        context.user_data.pop("sendcode_temp_password", None)
        context.user_data.pop("sendcode_temp_timestamp", None)
        context.user_data.pop("state", None)

async def filter_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    chat = update.effective_chat
    user = update.effective_user
    chat_id = chat.id
    user_id = user.id
    if chat.type not in ["group", "supergroup"]:
        return
    if user.is_bot:
        return
    if await is_chat_locked(chat_id):
        try:
            await update.message.delete()
            await safe_send_markdown(context.bot, chat_id, f"🔒 المجموعة مقفلة من قبل المشرف", 5)
        except:
            pass
        return
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms["can_act"]:
        return
    if not await db_check_slow_mode(chat_id, user_id):
        try:
            await update.message.delete()
            await safe_send_markdown(context.bot, chat_id, f"⏱️ **وضع بطيء مفعل**\n@{user.username or str(user_id)} يرجى الانتظار قبل إرسال رسالة جديدة", 3)
        except:
            pass
        return
    if NSFW_ENABLED:
        if update.message.photo:
            file = await context.bot.get_file(update.message.photo[-1].file_id)
            if file.file_size > NSFW_MAX_FILE_SIZE:
                await update.message.reply_text(f"⚠️ حجم الصورة كبير جداً للتحليل (الحد الأقصى {NSFW_MAX_FILE_SIZE // (1024*1024)} ميجابايت)")
                return
            try:
                file_bytes = await file.download_as_bytearray()
                cache_key = hashlib.md5(file_bytes).hexdigest()
                result = await check_nsfw_cached(file_bytes, cache_key)
                if result.get("error"):
                    logger.warning(f"NSFW check error: {result.get('error')}")
                elif result.get("nsfw", False):
                    await update.message.delete()
                    warning = f"🚫 **تم حذف الصورة**\n\nنسبة المحتوى غير اللائق: {result['nsfw_score'] * 100:.0f}%\n@{user.username or str(user_id)} يرجى احترام قوانين المجموعة."
                    await safe_send_markdown(context.bot, chat_id, warning)
                    security_settings = await db_get_security_settings(chat_id)
                    await apply_penalty(context.bot, chat_id, user_id, security_settings)
                    return
            except Exception as e:
                logger.error(f"NSFW image analysis error: {e}")
        elif update.message.video:
            if not CV2_AVAILABLE:
                logger.warning("cv2 not installed, skipping NSFW video check")
                return
            file = await context.bot.get_file(update.message.video.file_id)
            if file.file_size > NSFW_MAX_VIDEO_SIZE:
                await update.message.reply_text(f"⚠️ حجم الفيديو كبير جداً للتحليل (الحد الأقصى {NSFW_MAX_VIDEO_SIZE // (1024*1024)} ميجابايت)")
                return
            try:
                file_bytes = await file.download_as_bytearray()
                result = await check_nsfw_video(file_bytes, frames=NSFW_FRAMES)
                if result.get("error"):
                    logger.warning(f"NSFW video check error: {result.get('error')}")
                elif result.get("nsfw", False):
                    await update.message.delete()
                    warning = f"🚫 **تم حذف الفيديو**\n\nنسبة المحتوى غير اللائق: {result['nsfw_score'] * 100:.0f}%\nتم تحليل {result.get('frames_analyzed', 0)} إطار.\n@{user.username or str(user_id)} يرجى احترام قوانين المجموعة."
                    await safe_send_markdown(context.bot, chat_id, warning)
                    security_settings = await db_get_security_settings(chat_id)
                    await apply_penalty(context.bot, chat_id, user_id, security_settings)
                    return
            except Exception as e:
                logger.error(f"NSFW video analysis error: {e}")
    user_reply_enabled = await db_get_user_auto_reply_status(user_id)
    if not user_reply_enabled:
        return
    settings = await db_get_auto_reply_settings(chat_id)
    if not settings["enabled"]:
        return
    if settings["only_admins"]:
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            return
    if settings["ignore_bots"] and update.effective_user.is_bot:
        return
    security_settings = await db_get_security_settings(chat_id)
    text = update.message.text or update.message.caption or ""
    if security_settings.get("delete_banned_words"):
        banned_word = await db_contains_banned_word(text, chat_id)
        if banned_word:
            try:
                await update.message.delete()
                await safe_send_markdown(context.bot, chat_id, f"🚫 **كلمة محظورة**\n@{user.username or str(user_id)} الكلمة `{banned_word}` غير مسموح بها")
            except:
                pass
            await apply_penalty(context.bot, chat_id, user_id, security_settings)
            return
    if security_settings.get("links") and contains_link(text):
        try:
            await update.message.delete()
            await safe_send_markdown(context.bot, chat_id, f"🔗 **الروابط غير مسموح بها**\n@{user.username or str(user_id)}")
        except:
            pass
        await apply_penalty(context.bot, chat_id, user_id, security_settings)
        return
    if security_settings.get("mentions") and contains_mention(text):
        try:
            await update.message.delete()
            await safe_send_markdown(context.bot, chat_id, f"@ **المعرفات غير مسموح بها**\n@{user.username or str(user_id)}")
        except:
            pass
        await apply_penalty(context.bot, chat_id, user_id, security_settings)
        return
    reply = None
    text_lower = text.lower()
    if text_lower:
        cached_reply = await get_cached_reply(text_lower)
        if cached_reply:
            reply = cached_reply
        else:
            reply = await db_get_reply(text_lower)
            if reply:
                await set_cached_reply(text_lower, reply)
    if not reply and text_lower in ALL_REPLIES:
        reply = ALL_REPLIES[text_lower]
        await set_cached_reply(text_lower, reply)
    if not reply:
        for keyword, response in ALL_REPLIES.items():
            if keyword in text_lower:
                reply = response
                await set_cached_reply(keyword, reply)
                break
    if reply:
        try:
            await update.message.reply_text(reply)
        except Exception as e:
            logger.error(f"Failed to send reply: {e}")

async def get_cached_reply(keyword: str) -> Optional[str]:
    now = time.time()
    if keyword in _reply_cache:
        if now - _reply_cache_time.get(keyword, 0) < _REPLY_CACHE_TTL:
            return _reply_cache[keyword]
        else:
            del _reply_cache[keyword]
            if keyword in _reply_cache_time:
                del _reply_cache_time[keyword]
    return None

async def set_cached_reply(keyword: str, reply: str):
    _reply_cache[keyword] = reply
    _reply_cache_time[keyword] = time.time()

async def clear_reply_cache():
    _reply_cache.clear()
    _reply_cache_time.clear()

async def global_error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        error = context.error
        error_id = advanced_logger.log_error("Update error", error, {"user_id": update.effective_user.id if update and update.effective_user else None, "chat_id": update.effective_chat.id if update and update.effective_chat else None, "message": update.effective_message.text if update and update.effective_message else None})
        if isinstance(error, Conflict):
            logger.warning(f"⚠️ Conflict error: {error}")
            return
        if isinstance(error, Forbidden):
            logger.warning(f"⚠️ Forbidden error: {error}")
            if update and update.effective_chat:
                try:
                    await context.bot.send_message(chat_id=PRIMARY_OWNER_ID, text=f"⚠️ **البوت محظور أو ليس لديه صلاحيات في:**\n{update.effective_chat.title}\nID: `{update.effective_chat.id}`")
                except:
                    pass
            return
        if isinstance(error, TimedOut):
            logger.warning(f"⏱️ Timeout error: {error}")
            return
        if update and update.effective_user and context and context.bot:
            try:
                await safe_send_markdown(context.bot, update.effective_user.id, f"❌ **حدث خطأ غير متوقع** (الرمز: `{error_id}`)\n\nتم تسجيل المشكلة وسيتم حلها قريباً. جرب مرة أخرى لاحقاً.")
            except Exception as e:
                logger.error(f"Failed to send error message to user: {e}")
                try:
                    await context.bot.send_message(chat_id=update.effective_user.id, text=f"❌ حدث خطأ (الرمز: {error_id}). سيتم حله قريباً.")
                except:
                    pass
        if PRIMARY_OWNER_ID and context and context.bot:
            try:
                error_text = f"🚨 **خطأ في البوت** (الرمز: {error_id})\n\n"
                error_text += f"📌 المستخدم: {update.effective_user.id if update and update.effective_user else 'غير معروف'}\n"
                error_text += f"⚠️ الخطأ: `{str(error)[:300]}`\n"
                if update and update.effective_message and update.effective_message.text:
                    error_text += f"📝 الرسالة: `{update.effective_message.text[:100]}`\n"
                await context.bot.send_message(PRIMARY_OWNER_ID, error_text, parse_mode="MarkdownV2")
            except Exception as e:
                logger.error(f"Failed to send error notification to developer: {e}")
    except Exception as e:
        logger.error(f"Global error handler failed: {e}")

class AdvancedLogger:
    def __init__(self):
        self.loggers = {}
        self._setup_loggers()

    def _setup_loggers(self):
        error_logger = logging.getLogger("error_logger")
        error_logger.setLevel(logging.ERROR)
        error_handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
        error_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        error_logger.addHandler(error_handler)
        self.loggers["error"] = error_logger
        access_logger = logging.getLogger("access_logger")
        access_logger.setLevel(logging.INFO)
        access_handler = logging.FileHandler(ACCESS_LOG, encoding="utf-8")
        access_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
        access_logger.addHandler(access_handler)
        self.loggers["access"] = access_logger
        security_logger = logging.getLogger("security_logger")
        security_logger.setLevel(logging.WARNING)
        security_handler = logging.FileHandler(SECURITY_LOG, encoding="utf-8")
        security_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        security_logger.addHandler(security_handler)
        self.loggers["security"] = security_logger

    def log_error(self, message: str, error: Exception = None, context: dict = None):
        error_id = secrets.token_hex(4)
        log_msg = f"[{error_id}] {message}"
        if error:
            log_msg += f" - {error}"
        if context:
            log_msg += f" - السياق: {json.dumps(context, default=str)[:200]}"
        self.loggers["error"].error(log_msg)
        traceback.print_exc()
        return error_id

    def log_access(self, user_id: int, action: str, details: dict = None):
        log_msg = f"User: {user_id} - Action: {action}"
        if details:
            log_msg += f" - {json.dumps(details, default=str)[:100]}"
        self.loggers["access"].info(log_msg)

    def log_security(self, event: str, user_id: int, details: dict = None, severity: str = "INFO"):
        log_msg = f"[{severity}] {event} - User: {user_id}"
        if details:
            log_msg += f" - {json.dumps(details, default=str)[:200]}"
        self.loggers["security"].warning(log_msg)

advanced_logger = AdvancedLogger()

def log_error(error: Exception, context: dict = None) -> str:
    return advanced_logger.log_error("Error", error, context)
