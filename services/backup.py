import asyncio
import shutil
from datetime import datetime
from config import BACKUP_DIR, DB_PATH, MAX_BACKUPS

async def auto_backup_loop():
    while True:
        await asyncio.sleep(86400)  # كل 24 ساعة
        try:
            backup_file = BACKUP_DIR / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            shutil.copy2(DB_PATH, backup_file)
            
            backups = sorted(BACKUP_DIR.glob("backup_*.db"), key=lambda x: x.stat().st_mtime, reverse=True)
            for old in backups[MAX_BACKUPS:]:
                old.unlink()
            
            print(f"✅ تم إنشاء نسخة احتياطية: {backup_file.name}")
        except Exception as e:
            print(f"⚠️ فشل النسخ الاحتياطي: {e}")
