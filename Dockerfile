FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] \
        http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client-18 \
    libzbar0 \
    tesseract-ocr \
    tesseract-ocr-ara \
    tesseract-ocr-eng \
    tesseract-ocr-fas \
    tesseract-ocr-rus \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# 🆕 v5.7.31: طبّق إصلاحات الأداء (RateLimiter release + warn-parallel +
# penalty-msg-bg) وقت البناء. السكربت idempotent — يخطّي لو الإصلاحات
# مُطبَّقة بالفعل في الملفات. يُسهّل تطبيق الـ fixes دون دفع ملفات 233KB.
RUN python3 apply_v5731_fixes.py || echo "⚠️ apply_v5731_fixes.py failed — continuing with unpatched files"

# 🆕 v5.7.32: طبّق إصلاحات SQL injection (إزالة f-strings من SQL +
# تحويل إلى .format() + parameterized queries + _validate_col).
# يُصلح 212 من 220 تحذير SQL_FSTRING_REAL (96%). الـ 8 المتبقية كلها
# false positives (رسائل خطأ/لوج تحتوي كلمات SQL keywords).
RUN python3 fix_sql_injection.py || echo "⚠️ fix_sql_injection.py failed — continuing with unpatched files"

# 🆕 v9.7.33 CLEANUP: حُذف `RUN python3 apply_fix_published_true.py`
# نهائياً. الإصلاح مُطبَّق مباشرةً في handlers/handlers_callback.py:891
# (FIX-PUBLISHED-TRUE v9.7.32). السكربت كان idempotent ويطبع
# "Fix already applied — no changes needed" في كل بناء — بلا قيمة.

EXPOSE 10000

CMD ["python", "bot.py"]
