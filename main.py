#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import sys
import nest_asyncio
from bot import run_bot

# تطبيق nest_asyncio لحل مشكلة event loop
nest_asyncio.apply()

if __name__ == "__main__":
    try:
        print("🚀 جاري تشغيل البوت...")
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف البوت")
    except Exception as e:
        print(f"❌ خطأ: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
