#!/bin/bash
cd ~/reelax_bot
python3 -c "
import asyncio
from reelax_bot import main
asyncio.run(main())
"
