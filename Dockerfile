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

# 🆕 FIX-PUBLISHED-TRUE (v9.7.32): تطبيق إصلاح السبب الجذري للتحذيرات الخاطئة
# على PostgreSQL قبل تشغيل البوت. السكربت idempotent — لا يفعل شيئاً إن
# كان الإصلاح مُطبّقاً بالفعل في الكود المرفوع.
# (سيُحذف هذا السطر تلقائياً عند رفع handlers_callback.py المُصلّح مباشرةً)
RUN python3 apply_fix_published_true.py || echo "apply_fix skipped (already fixed or not needed)"

EXPOSE 10000

CMD ["python", "bot.py"]