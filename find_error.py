import os

search_text = "Total price must be positive"
found = False

print("🔍 جاري البحث في ملفات المشروع...")
for root, dirs, files in os.walk("."):
    # تجاهل مجلدات النظام
    if ".git" in root or "__pycache__" in root or "venv" in root:
        continue
        
    for file in files:
        if file.endswith(".py"):
            path = os.path.join(root, file)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        if search_text in line:
                            print(f"\n✅ تم العثور عليه في الملف: {path}")
                            print(f"📍 رقم السطر: {i}")
                            print(f"💻 الكود: {line.strip()}")
                            found = True
            except Exception:
                pass

if not found:
    print("❌ لم يتم العثور على النص. تأكد من تشغيل السكربت في المجلد الرئيسي.")