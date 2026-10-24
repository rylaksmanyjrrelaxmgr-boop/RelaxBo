
import asyncio
from database import DB

async def fix_month_plan():
    await DB.initialize()
    
    # 1. فحص الباقات
    plans = await DB.fetchall("SELECT id, name, price, is_active FROM plans WHERE name LIKE '%شهر%'")
    print("\n📋 الباقات التي تحتوي على كلمة 'شهر':")
    for p in plans:
        print(f"ID: {p['id']} | الاسم: '{p['name']}' | السعر: {p['price']} | نشط: {p['is_active']}")

    # 2. إصلاح السعر فوراً إذا كان 0
    updated = await DB.execute(
        "UPDATE plans SET price = 75, currency = 'XTR', is_active = 1 WHERE name LIKE '%شهر%'"
    )
    if updated > 0:
        print("\n✅ تم إصلاح الباقة! السعر الآن 75 نجمة.")
        print("🔄 جرب الآن الضغط على زر 'شهر' في البوت.")
    else:
        print("\n❌ لم يتم العثور على الباقة لتحديثها.")

asyncio.run(fix_month_plan())