FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    android-tools-adb \
    ca-certificates \
    curl \
    fonts-liberation \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY apps ./apps
COPY workers ./workers

RUN pip install --no-cache-dir uv \
    && uv pip install --system . \
    && python -m playwright install --with-deps chromium \
    && mkdir -p runtime/storage runtime/artifacts runtime/profiles runtime/android-backups

EXPOSE 8080

CMD ["uvicorn", "media_automata.api:app", "--host", "0.0.0.0", "--port", "8080"]
