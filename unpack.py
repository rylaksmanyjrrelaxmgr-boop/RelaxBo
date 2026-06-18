import urllib.request
url = "https://raw.githubusercontent.com/Reelaaax/reelax_bot/main/reelax_bot.py"
try:
    urllib.request.urlretrieve(url, "reelax_bot.py")
    print("✅ تم تحميل البوت بنجاح. شغله باستخدام: python3 reelax_bot.py")
except Exception as e:
    print(f"❌ فشل التحميل: {e}")
    print("قد يكون الرابط غير صحيح. راسل المطور على تليجرام: @Reelaaaxxbot")
