#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import sys
import nest_asyncio
from bot import run_bot

nest_asyncio.apply()

async def main():
    await run_bot()

if __name__ == "__main__":
    try:
        print("🚀 جاري تشغيل البوت...")
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف البوت")
    except Exception as e:
        print(f"❌ خطأ: {e}")
        sys.exit(1)
