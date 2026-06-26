import re

with open('reelax_bot.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# إصلاح جميع أخطاء المسافات
fixed_lines = []
for i, line in enumerate(lines):
    # إذا كان السطر يحتوي على return web.json_response مع مسافات غير صحيحة
    if 'return web.json_response' in line:
        # حساب المسافات الصحيحة (مضاعفات 4)
        indent = len(line) - len(line.lstrip())
        correct_indent = (indent // 4) * 4
        if indent != correct_indent:
            line = ' ' * correct_indent + line.lstrip()
    
    # إصلاح IndentationError عام
    if line.strip() and not line.strip().startswith(('#', '"""', "'''")):
        # إذا كان السطر يبدأ بـ except: أو finally: أو else:
        if re.match(r'^[ ]*(except|finally|else)[ :]', line):
            indent = len(line) - len(line.lstrip())
            correct_indent = max(0, ((indent // 4) - 1) * 4)
            if indent != correct_indent:
                line = ' ' * correct_indent + line.lstrip()
    
    fixed_lines.append(line)

content = ''.join(fixed_lines)

# إصلاح return بدون مسافات كافية
content = re.sub(r'\n([ ]{0,3})return web\.json_response\(', lambda m: '\n' + ' ' * (len(m.group(1)) + 4) + 'return web.json_response(', content)

# إصلاح try/except
content = re.sub(r'(\n[ ]+)try:\s*\n[ ]+except', r'\1try:\n\1    pass\n\1except', content)

with open('reelax_bot.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ تم إصلاح جميع مشاكل المسافات")
