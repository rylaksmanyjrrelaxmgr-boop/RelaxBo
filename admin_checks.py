import time
import logging
from typing import Optional
from telegram import Update
from telegram.ext import ContextTypes
from config import PRIMARY_OWNER_ID, CACHETOOLS_AVAILABLE, _admin_cache, _admin_cache_time, _ADMIN_CACHE_TTL
from database import db_is_hidden_owner, db_is_hidden_admin, is_bot_admin

logger = logging.getLogger(__name__)

def _set_admin_cache(key: str, value: bool):
    if CACHETOOLS_AVAILABLE:
        _admin_cache[key] = value
    else:
        _admin_cache[key] = value
        _admin_cache_time[key] = time.time()

def _get_admin_cache(key: str) -> Optional[bool]:
    if CACHETOOLS_AVAILABLE:
        return _admin_cache.get(key, None)
    if key in _admin_cache:
        if time.time() - _admin_cache_time.get(key, 0) < _ADMIN_CACHE_TTL:
            return _admin_cache[key]
        else:
            del _admin_cache[key]
            if key in _admin_cache_time:
                del _admin_cache_time[key]
    return None

async def check_admin_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    user_id = user.id
    chat = update.effective_chat
    if not chat:
        return False
    chat_id = chat.id
    chat_type = chat.type

    if user_id == PRIMARY_OWNER_ID:
        return True

    cache_key = f"{chat_id}:{user_id}"
    cached = _get_admin_cache(cache_key)
    if cached is not None:
        return cached

    try:
        if await is_bot_admin(user_id):
            _set_admin_cache(cache_key, True)
            return True
    except:
        pass

    if chat_type == 'private':
        _set_admin_cache(cache_key, False)
        return False

    if chat_type in ['group', 'supergroup']:
        try:
            if await db_is_hidden_owner(chat_id, user_id):
                _set_admin_cache(cache_key, True)
                return True
        except:
            pass

        try:
            if await db_is_hidden_admin(chat_id, user_id):
                _set_admin_cache(cache_key, True)
                return True
        except:
            pass

        if update.message and update.message.sender_chat:
            sender_chat = update.message.sender_chat
            try:
                bot_member = await context.bot.get_chat_member(sender_chat.id, context.bot.id)
                if bot_member.status in ['administrator', 'creator']:
                    try:
                        member = await context.bot.get_chat_member(sender_chat.id, user_id)
                        if member.status in ['administrator', 'creator']:
                            _set_admin_cache(cache_key, True)
                            return True
                    except:
                        pass
                    if await db_is_hidden_admin(sender_chat.id, user_id) or await db_is_hidden_owner(sender_chat.id, user_id):
                        _set_admin_cache(cache_key, True)
                        return True
            except:
                pass

        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            if member.status in ['administrator', 'creator']:
                _set_admin_cache(cache_key, True)
                return True
        except:
            pass

        _set_admin_cache(cache_key, False)
        return False

    return False
