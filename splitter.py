import os
import re

def split_code(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # تقسيم الكود بناءً على الكلمات المفتاحية
    parts = re.split(r'(^async def |^def |^class )', content, flags=re.M)
    
    # إنشاء المجلدات إذا لم تكن موجودة
    if not os.path.exists('modules'):
        os.makedirs('modules')

    # توزيع الدوال في ملفات
    current_module = "modules/utils.py"
    for i in range(1, len(parts), 2):
        block = parts[i] + parts[i+1]
        if "db_" in block or "database" in block:
            current_module = "modules/database.py"
        elif "cmd_" in block or "handler" in block:
            current_module = "modules/handlers.py"
        else:
            current_module = "modules/utils.py"
            
        with open(current_module, 'a', encoding='utf-8') as f:
            f.write(block + "\n\n")

    print("✅ تم تقسيم الملف بنجاح إلى مجلد 'modules'!")

split_code('reelax_bot.py')

