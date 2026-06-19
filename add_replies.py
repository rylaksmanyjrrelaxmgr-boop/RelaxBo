import sqlite3
import random
import os
import sys

# 500 رد جاهزة (متنوعة)
REPLIES = [
    ("مرحباً", "أهلاً بك! كيف يمكنني مساعدتك؟ 😊"),
    ("السلام عليكم", "وعليكم السلام ورحمة الله وبركاته 🌹"),
    ("شكراً", "العفو، تحت أمرك دائماً 🤍"),
    ("جزاك الله خير", "وإياك يا صديقي 🤲"),
    ("كيف حالك", "الحمد لله، أنا بخير. وأنت كيف حالك؟ 😊"),
    ("تصبح على خير", "تصبح على خير ومساء الورد 🌙"),
    ("صباح الخير", "صباح النور والسرور ☀️"),
    ("مساء الخير", "مساء الورد والفل 🌸"),
    ("رفع", "تم رفع المنشور ✅"),
    ("نشر", "✅ سيتم النشر تلقائياً خلال دقائق"),
    ("مساعدة", "استخدم الأوامر التالية: /start, /help, /security, /trial, /subscribe"),
    ("بوت", "أنا ريلاكس مانيجر، تحت أمرك 🤖"),
    ("تحديث", "آخر تحديث: إصلاح مشاكل النشر وتحسين الأداء 📦"),
    ("المطور", "@RelaxMgr - يمكنك التواصل معه للاستفسارات 👨‍💻"),
    ("قناة", "أضف قناة عبر أمر /addchannel أو من القائمة الرئيسية 📡"),
    ("منشور", "أرسل المنشورات عبر زر إضافة 15 منشوراً 📝"),
    ("جدول", "استخدم /schedule لجدولة المنشورات 📅"),
    ("أمان", "استخدم /security لضبط إعدادات الأمان 🔐"),
    ("اشتراك", "استخدم /subscribe للاشتراك المميز 💎"),
    ("تجربة", "استخدم /trial للحصول على نسخة تجريبية مجانية 🎁"),
    ("رتبة", "استخدم /rank لمعرفة رتبتك ونقاطك ⭐"),
    ("معلومات", f"البوت: ريلاكس مانيجر\nالإصدار: 17.3.4\nالمطور: @RelaxMgr\nالقناة: @Reelaaaxbot 📢"),
    ("الردود", "هذه قائمة بالردود التلقائية المتوفرة 📋"),
    ("اللغات", "متاح: العربية، الإنجليزية، الفرنسية، التركية، الصينية، الروسية 🌐"),
    ("النسخ الاحتياطي", "يتم عمل نسخ احتياطي تلقائي للبيانات 💾"),
    ("السحابة", "جميع البيانات محفوظة في سحابة آمنة ☁️"),
    ("الحماية", "نظام حماية متكامل ضد الروابط والمعرفات والكلمات المحظورة 🛡️"),
    ("العقوبات", "عقوبات تلقائية: طرد، حظر، كتم حسب الإعدادات ⚖️"),
    ("الترحيب", "يمكن تفعيل رسائل ترحيب وداع للمجموعات 🎯"),
    ("القفل", "استخدم /lock و /unlock للتحكم بقفل المجموعة 🔒"),
    ("اللوحة", "استخدم /panel للوحة تحكم المجموعة 🛠️"),
    ("الحظر", "استخدم /ban لحظر مستخدم 🚫"),
    ("الكتم", "استخدم /mute لكتم مستخدم 🔇"),
    ("الطرد", "استخدم /kick لطرد مستخدم 👢"),
    ("التقييد", "استخدم /restrict لتقييد مستخدم 🔒"),
    ("التثبيت", "استخدم /pin لتثبيت رسالة 📌"),
    ("الدعم", "للتواصل مع الدعم استخدم /support 🛟"),
    ("التطوير", "مطور البوت: @RelaxMgr يسعد بتلقي اقتراحاتكم 💡"),
]

# توليد 500 رد بتنوع إضافي (تركيبات مختلفة)
def generate_replies():
    base_replies = REPLIES[:]
    # إضافة ردود متنوعة إضافية لتصل إلى 500
    greetings = ["أهلاً", "مرحباً", "أهلاً وسهلاً", "حيّاك الله", "نورت", "تشرفنا"]
    thanks = ["شكراً", "مشكور", "يعطيك العافية", "بارك الله فيك", "جزاك الله خيراً", "الله يجزاك خير"]
    farewell = ["مع السلامة", "باي", "إلى اللقاء", "وداعاً", "في أمان الله"]
    help_phrases = ["كيف أساعدك؟", "أنا هنا لخدمتك", "تحت أمرك", "كيف أقدر أفيدك؟", "تفضل اسأل"]

    for i in range(500):
        if i < len(base_replies):
            continue
        if i % 4 == 0:
            k = random.choice(greetings) + " " + random.choice(["جميعاً", "يا صديقي", "أستاذي", "أخي"])
            v = random.choice(help_phrases) + " 😊"
        elif i % 4 == 1:
            k = random.choice(thanks)
            v = random.choice(["العفو", "تحت أمرك", "الله يعافيك", "وأنا في خدمتك"]) + " 🤍"
        elif i % 4 == 2:
            k = random.choice(farewell)
            v = random.choice(["وداعاً", "في أمان الله", "مع السلامة", "نتمنى رؤيتك مجدداً"]) + " 👋"
        else:
            k = "رد" + str(i)
            v = random.choice(["تم الرد بنجاح ✅", "حسناً!", "جاري التنفيذ...", "تم 🎯", "مفهوم 📝"])
        base_replies.append((k, v))
    return base_replies[:500]

# دالة لإضافة الردود (SQLite)
def add_replies_sqlite():
    db_path = "bot_data.db"
    if not os.path.exists(db_path):
        print("❌ ملف قاعدة البيانات غير موجود!")
        return
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS group_replies (keyword TEXT PRIMARY KEY, reply TEXT)")
    replies = generate_replies()
    inserted = 0
    for keyword, reply in replies:
        try:
            cursor.execute("INSERT OR REPLACE INTO group_replies (keyword, reply) VALUES (?, ?)", (keyword, reply))
            inserted += 1
        except Exception as e:
            print(f"⚠️ فشل إضافة {keyword}: {e}")
    conn.commit()
    conn.close()
    print(f"✅ تم إضافة {inserted} رد إلى SQLite")

# دالة لإضافة الردود (PostgreSQL/Supabase)
async def add_replies_postgres():
    import asyncpg
    import os
    db_url = os.getenv("DATABASE_URL") or input("أدخل DATABASE_URL (postgresql://...): ")
    if not db_url:
        print("❌ لم يتم توفير رابط قاعدة البيانات")
        return
    try:
        conn = await asyncpg.connect(db_url)
        await conn.execute("CREATE TABLE IF NOT EXISTS group_replies (keyword TEXT PRIMARY KEY, reply TEXT)")
        replies = generate_replies()
        inserted = 0
        for keyword, reply in replies:
            try:
                await conn.execute("INSERT INTO group_replies (keyword, reply) VALUES ($1, $2) ON CONFLICT (keyword) DO UPDATE SET reply = $2", keyword, reply)
                inserted += 1
            except Exception as e:
                print(f"⚠️ فشل إضافة {keyword}: {e}")
        await conn.close()
        print(f"✅ تم إضافة {inserted} رد إلى PostgreSQL")
    except Exception as e:
        print(f"❌ فشل الاتصال: {e}")

# التشغيل
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "postgres":
        import asyncio
        asyncio.run(add_replies_postgres())
    else:
        add_replies_sqlite()
