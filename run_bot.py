import sys, os, asyncio
sys.path.insert(0, '.')
import reelax_bot
reelax_bot.lock_socket = None
asyncio.run(reelax_bot.main())
