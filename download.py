import requests
import os

# تحميل الكود الكامل للبوت
url = "https://raw.githubusercontent.com/RelaxMgr/RelaxManagerBot/main/bot.py"
response = requests.get(url)

if response.status_code == 200:
    with open("bot.py", "w", encoding="utf-8") as f:
        f.write(response.text)
    print("✅ تم تحميل الكود الكامل بنجاح!")
else:
    print("❌ فشل التحميل")
