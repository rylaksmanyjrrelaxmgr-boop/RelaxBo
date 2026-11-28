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

# v5.7.31: RateLimiter release + warn-parallel + penalty-msg-bg
RUN python3 apply_v5731_fixes.py || echo "apply_v5731_fixes.py failed"

# v5.7.32: SQL injection fixes (f-string removal + .format() + parameterized)
RUN python3 fix_sql_injection.py || echo "fix_sql_injection.py failed"

# v5.7.33: DB pool min=20 + RateLimiter 30 concurrent + send timeout 2s
RUN python3 fix_perf_v5733.py || echo "fix_perf_v5733.py failed"

# v5.7.34: Fix managed_bots schema (id->bot_id, username->name)
RUN python3 fix_managed_bots_schema.py || echo "fix_managed_bots_schema.py failed"

# v5.7.34: Generate locales/translations.json from individual language files
RUN python3 generate_translations.py || echo "generate_translations.py failed"

# v5.7.36: Add _do_broadcast method (broadcast feature was broken)
RUN python3 fix_broadcast.py || echo "fix_broadcast.py failed"

# v5.7.37: /health command + weekly perf report + improvements
RUN python3 fix_improvements.py || echo "fix_improvements.py failed"

# v5.7.38: Add Health button to admin panel
RUN python3 fix_admin_health_button.py || echo "fix_admin_health_button.py failed"

EXPOSE 10000

CMD ["python", "bot.py"]
