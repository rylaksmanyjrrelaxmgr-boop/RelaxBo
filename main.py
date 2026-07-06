#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import sys
from bot import run_bot

if __name__ == "__main__":
    try:
        print("🚀 جاري تشغيل البوت...")
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف البوت")
    except Exception as e:
        print(f"❌ خطأ: {e}")
        sys.exit(1)
