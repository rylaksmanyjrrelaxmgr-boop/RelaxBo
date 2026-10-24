import os

search_terms = ["send_invoice", "LabeledPrice", "XTR"]
found = False

print("🔍 جاري البحث عن ملف الفواتير...")
for root, dirs, files in os.walk("."):
    if ".git" in root or "__pycache__" in root or "venv" in root:
        continue
    for file in files:
        if file.endswith(".py"):
            path = os.path.join(root, file)
            if "find_error.py" in path:
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        if "send_invoice" in line or "LabeledPrice" in line:
                            print(f"\n✅ الملف: {path}")
                            print(f"📍 السطر: {i}")
                            print(f"💻 الكود: {line.strip()}")
                            found = True
            except Exception:
                pass

if not found:
    print("❌ لم يتم العثور على دالة send_invoice")