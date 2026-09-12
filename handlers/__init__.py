#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers/__init__.py - حزمة معالجات البوت
==========================================
تجمع جميع معالجات الأوامر والرسائل والأزرار في مكان واحد لتسهيل الاستيراد.

🆕 v2:
  - إضافة chat_member (معالج تحديثات المشرفين)
  - إضافة handlers_channels_list (قائمة القنوات الجديدة)
"""

from .handlers_command import CommandHandlers
from .handlers_callback import CallbackHandlers
from .handlers_message import MessageHandlers

# ✅ معالج تحديثات المشرفين (module — يُستدعى بـ chat_member.register(app))
try:
    from . import chat_member
    CHAT_MEMBER_AVAILABLE = True
except ImportError:
    chat_member = None
    CHAT_MEMBER_AVAILABLE = False

# ✅ قائمة القنوات الجديدة (module — يُستدعى بـ register_channels_list_handlers(app))
try:
    from . import handlers_channels_list
    CHANNELS_LIST_AVAILABLE = True
except ImportError:
    handlers_channels_list = None
    CHANNELS_LIST_AVAILABLE = False


# قائمة بجميع الكلاسات المصدرة
__all__ = [
    "CommandHandlers",
    "CallbackHandlers",
    "MessageHandlers",
    "chat_member",
    "handlers_channels_list",
]


def get_all_handlers():
    """
    إرجاع قاموس بجميع معالجات البوت.
    """
    return {
        "command": CommandHandlers,
        "callback": CallbackHandlers,
        "message": MessageHandlers,
        "chat_member": chat_member,
        "channels_list": handlers_channels_list,
    }