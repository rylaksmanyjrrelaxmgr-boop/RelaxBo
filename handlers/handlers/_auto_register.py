#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers/_auto_register.py - تسجيل تلقائي لكل handlers القنوات
================================================================================
الاستخدام في bot.py:
    from handlers._auto_register import register_all_channel_handlers
    register_all_channel_handlers(application)
================================================================================
"""

import logging

logger = logging.getLogger(__name__)


def register_all_channel_handlers(application):
    """
    تسجيل تلقائي لكل handlers القنوات.
    يجرب استيراد كل ملف موجود ويسجل ما ينجح.
    """
    registered = []

    # 1) handlers_channels_list.py (الجديد)
    try:
        from handlers.handlers_channels_list import (
            register_channels_list_handlers,
        )
        if register_channels_list_handlers(application):
            registered.append("handlers_channels_list")
    except ImportError as e:
        logger.warning(f"⚠️ handlers_channels_list غير موجود: {e}")
    except Exception as e:
        logger.error(f"❌ فشل تسجيل handlers_channels_list: {e}")

    # 2) handlers_channels.py (القديم — إن كان موجوداً)
    try:
        from handlers.handlers_channels import (
            register_handlers as register_channels_handlers,
        )
        register_channels_handlers(application)
        registered.append("handlers_channels")
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"handlers_channels: {e}")

    # 3) أي ملفات handlers أخرى
    other_modules = [
        ("handlers.handlers_start", "register_handlers"),
        ("handlers.handlers_callback", "register_handlers"),
    ]

    for module_name, func_name in other_modules:
        try:
            module = __import__(module_name, fromlist=[func_name])
            func = getattr(module, func_name, None)
            if func:
                func(application)
                registered.append(module_name)
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"{module_name}: {e}")

    logger.info(f"✅ مسجّل: {', '.join(registered)}")
    return registered