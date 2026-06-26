#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
database_ops.py - عمليات قاعدة البيانات الأساسية
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import logging
from database import get_collection
from models import User, Channel, Post, Schedule

logger = logging.getLogger(__name__)


# ===================== دوال المستخدمين =====================

async def db_register_user(user_id: int) -> bool:
    """تسجيل مستخدم جديد"""
    users = get_collection("users")
    
    existing = await users.find_one({"user_id": user_id})
    if existing:
        return False
    
    user = User(user_id=user_id)
    await users.insert_one(user.to_dict())
    return True


async def db_get_user(user_id: int) -> Optional[Dict]:
    """جلب بيانات المستخدم"""
    users = get_collection("users")
    return await users.find_one({"user_id": user_id})


async def db_update_user(user_id: int, update_data: Dict) -> bool:
    """تحديث بيانات المستخدم"""
    users = get_collection("users")
    update_data["updated_at"] = datetime.utcnow().isoformat()
    
    result = await users.update_one(
        {"user_id": user_id},
        {"$set": update_data}
    )
    return result.modified_count > 0


async def db_get_all_users() -> List[Dict]:
    """جلب جميع المستخدمين"""
    users = get_collection("users")
    cursor = users.find({})
    return await cursor.to_list(length=None)


async def db_is_banned(user_id: int) -> bool:
    user = await db_get_user(user_id)
    return user.get("banned", False) if user else False


async def db_set_ban(user_id: int, banned: bool) -> bool:
    return await db_update_user(user_id, {"banned": banned})


async def db_has_active_subscription(user_id: int) -> bool:
    user = await db_get_user(user_id)
    if not user:
        return False
    
    subscription_end = user.get("subscription_end")
    if not subscription_end:
        return False
    
    try:
        end_date = datetime.fromisoformat(subscription_end)
        return end_date > datetime.utcnow()
    except:
        return False


async def db_activate_subscription(user_id: int, days: int) -> bool:
    user = await db_get_user(user_id)
    if not user:
        return False
    
    current_end = user.get("subscription_end")
    if current_end:
        try:
            end_date = datetime.fromisoformat(current_end)
            if end_date > datetime.utcnow():
                new_end = end_date + timedelta(days=days)
            else:
                new_end = datetime.utcnow() + timedelta(days=days)
        except:
            new_end = datetime.utcnow() + timedelta(days=days)
    else:
        new_end = datetime.utcnow() + timedelta(days=days)
    
    return await db_update_user(user_id, {"subscription_end": new_end.isoformat()})


async def db_auto_status(user_id: int) -> bool:
    user = await db_get_user(user_id)
    return user.get("auto_publish", True) if user else True


async def db_set_auto(user_id: int, enabled: bool) -> bool:
    return await db_update_user(user_id, {"auto_publish": enabled})


async def db_has_used_trial(user_id: int) -> bool:
    user = await db_get_user(user_id)
    return user.get("trial_used", False) if user else False


async def db_activate_trial(user_id: int) -> int:
    user = await db_get_user(user_id)
    if not user:
        return 0
    
    if user.get("trial_used", False):
        return 0
    
    end_date = (datetime.utcnow() + timedelta(days=30)).isoformat()
    await db_update_user(user_id, {"trial_used": True, "subscription_end": end_date})
    return 30


async def db_get_subscription_days_left(user_id: int) -> int:
    user = await db_get_user(user_id)
    if not user:
        return 0
    
    subscription_end = user.get("subscription_end")
    if not subscription_end:
        return 0
    
    try:
        end_date = datetime.fromisoformat(subscription_end)
        days = (end_date - datetime.utcnow()).days
        return max(0, days)
    except:
        return 0


# ===================== دوال القنوات =====================

async def db_add_channel(user_id: int, channel_id: str, channel_name: str) -> Optional[int]:
    channels = get_collection("channels")
    
    existing = await channels.find_one({"channel_id": channel_id})
    if existing:
        return None
    
    channel = Channel(channel_id=channel_id, user_id=user_id, channel_name=channel_name)
    result = await channels.insert_one(channel.to_dict())
    
    channel_data = await channels.find_one({"_id": result.inserted_id})
    return channel_data.get("_id") if channel_data else None


async def db_get_channels(user_id: int) -> List[Dict]:
    channels = get_collection("channels")
    cursor = channels.find({"user_id": user_id})
    return await cursor.to_list(length=None)


async def db_get_channel_info(channel_db_id: int) -> Optional[Dict]:
    channels = get_collection("channels")
    return await channels.find_one({"_id": channel_db_id})


async def db_delete_channel_by_id(user_id: int, channel_db_id: int) -> bool:
    channels = get_collection("channels")
    posts = get_collection("posts")
    schedule = get_collection("schedule")
    
    result = await channels.delete_one({"_id": channel_db_id, "user_id": user_id})
    if result.deleted_count == 0:
        return False
    
    await posts.delete_many({"channel_db_id": channel_db_id})
    await schedule.delete_many({"channel_db_id": channel_db_id})
    return True


async def db_get_active_channel(user_id: int) -> Optional[int]:
    user = await db_get_user(user_id)
    if user and user.get("active_channel"):
        return user["active_channel"]
    
    channels = get_collection("channels")
    channel = await channels.find_one({"user_id": user_id, "banned": False})
    return channel.get("_id") if channel else None


async def db_set_active_channel(user_id: int, channel_db_id: int) -> bool:
    return await db_update_user(user_id, {"active_channel": channel_db_id})


# ===================== دوال المنشورات =====================

async def db_save_posts(channel_db_id: int, posts_data: list) -> int:
    posts = get_collection("posts")
    
    posts_list = []
    for text_content, media_type, media_file_id in posts_data:
        post = Post(
            channel_db_id=channel_db_id,
            text=text_content,
            media_type=media_type,
            media_file_id=media_file_id
        )
        posts_list.append(post.to_dict())
    
    if posts_list:
        result = await posts.insert_many(posts_list)
        return len(result.inserted_ids)
    return 0


async def db_get_next_post(channel_db_id: int) -> Optional[Dict]:
    posts = get_collection("posts")
    
    post = await posts.find_one({
        "channel_db_id": channel_db_id,
        "published": False,
        "$or": [
            {"fail_count": {"$exists": False}},
            {"fail_count": {"$lt": 3}}
        ]
    })
    
    if post:
        post["id"] = post.pop("_id")
        return post
    return None


async def db_mark_published(post_id: int) -> bool:
    posts = get_collection("posts")
    result = await posts.update_one(
        {"_id": post_id},
        {"$set": {"published": True}}
    )
    return result.modified_count > 0


async def db_increment_fail_count(post_id: int) -> bool:
    posts = get_collection("posts")
    result = await posts.update_one(
        {"_id": post_id},
        {"$inc": {"fail_count": 1}}
    )
    return result.modified_count > 0


async def db_get_posts_count(channel_db_id: int) -> int:
    posts = get_collection("posts")
    return await posts.count_documents({"channel_db_id": channel_db_id})


async def db_get_published_count(channel_db_id: int) -> int:
    posts = get_collection("posts")
    return await posts.count_documents({"channel_db_id": channel_db_id, "published": True})


async def db_reset_all_posts_to_unpublished(channel_db_id: int) -> int:
    posts = get_collection("posts")
    result = await posts.update_many(
        {"channel_db_id": channel_db_id},
        {"$set": {"published": False}}
    )
    return result.modified_count


async def db_should_auto_recycle(channel_db_id: int) -> bool:
    total = await db_get_posts_count(channel_db_id)
    published = await db_get_published_count(channel_db_id)
    return total > 0 and published >= total


async def db_reset_posts_to_unpublished(channel_db_id: int, user_id: int = None) -> bool:
    posts = get_collection("posts")
    result = await posts.update_many(
        {"channel_db_id": channel_db_id},
        {"$set": {"published": False}}
    )
    return result.modified_count > 0


async def db_get_user_posts_for_channel(channel_db_id: int, limit=15) -> List[Dict]:
    posts = get_collection("posts")
    cursor = posts.find(
        {"channel_db_id": channel_db_id, "published": False}
    ).limit(limit)
    return await cursor.to_list(length=limit)


async def db_delete_single_post(post_id: int, user_id: int, channel_db_id: int) -> bool:
    posts = get_collection("posts")
    result = await posts.delete_one({"_id": post_id})
    return result.deleted_count > 0


async def db_get_user_unpublished_posts(user_id: int) -> int:
    # جلب القنوات أولاً
    channels = await db_get_channels(user_id)
    channel_ids = [ch["_id"] for ch in channels]
    
    posts = get_collection("posts")
    return await posts.count_documents({
        "channel_db_id": {"$in": channel_ids},
        "published": False
    })


async def db_get_user_total_posts(user_id: int) -> int:
    channels = await db_get_channels(user_id)
    channel_ids = [ch["_id"] for ch in channels]
    
    posts = get_collection("posts")
    return await posts.count_documents({
        "channel_db_id": {"$in": channel_ids}
    })


async def db_get_user_channels_count(user_id: int) -> int:
    channels = get_collection("channels")
    return await channels.count_documents({"user_id": user_id})


async def db_get_user_groups_count(user_id: int) -> int:
    # مؤقت - سيتم تعديله مع مجموعات MongoDB
    return 0


async def db_stats() -> tuple:
    users = get_collection("users")
    posts = get_collection("posts")
    channels = get_collection("channels")
    
    total_users = await users.count_documents({})
    banned_users = await users.count_documents({"banned": True})
    pending_posts = await posts.count_documents({"published": False})
    total_channels = await channels.count_documents({})
    
    return total_users, banned_users, pending_posts, 0, total_channels


# ===================== دوال حظر القنوات =====================

async def db_ban_channel(channel_id: str) -> bool:
    channels = get_collection("channels")
    result = await channels.update_one(
        {"channel_id": channel_id},
        {"$set": {"banned": True}}
    )
    return result.modified_count > 0


async def db_unban_channel(channel_id: str) -> bool:
    channels = get_collection("channels")
    result = await channels.update_one(
        {"channel_id": channel_id},
        {"$set": {"banned": False}}
    )
    return result.modified_count > 0


async def db_get_banned_channels() -> List[Dict]:
    channels = get_collection("channels")
    cursor = channels.find({"banned": True})
    return await cursor.to_list(length=None)


async def db_is_channel_banned(channel_id: str) -> bool:
    channels = get_collection("channels")
    channel = await channels.find_one({"channel_id": channel_id})
    return channel.get("banned", False) if channel else False

