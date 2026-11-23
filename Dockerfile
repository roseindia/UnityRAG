# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libpq5 curl \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY backend/requirements.txt backend/requirements.txt
RUN pip install \
    --no-cache-dir \
    --retries 10 \
    --timeout 120 \
    --index-url https://pypi.org/simple \
	-r backend/requirements.txt
COPY database /srv/database
COPY backend /srv/backend
RUN useradd --system --uid 10001 --home /srv rag && mkdir -p /srv/var/storage && chown -R rag /srv/var
USER rag
WORKDIR /srv/backend
ENV STORAGE_ROOT=/srv/var/storage
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS http://localhost:8000/health/live || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--workers", "2"]
