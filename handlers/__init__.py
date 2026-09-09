#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers/__init__.py - حزمة معالجات البوت
==========================================
تجمع جميع معالجات الأوامر والرسائل والأزرار في مكان واحد لتسهيل الاستيراد.
"""

from .handlers_command import CommandHandlers
from .handlers_callback import CallbackHandlers
from .handlers_message import MessageHandlers

# قائمة بجميع الكلاسات المصدرة
__all__ = [
    "CommandHandlers",
    "CallbackHandlers",
    "MessageHandlers",
]

# يمكن إضافة دالة مساعدة لاسترجاع جميع المعالجات دفعة واحدة (اختياري)
def get_all_handlers():
    """
    إرجاع قاموس بجميع معالجات البوت.
    """
    return {
        "command": CommandHandlers,
        "callback": CallbackHandlers,
        "message": MessageHandlers,
    }