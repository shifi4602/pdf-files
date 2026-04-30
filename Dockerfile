# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.10-slim AS builder

WORKDIR /app

# System build deps (needed to compile some wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.10-slim

# Tesseract OCR + Hebrew language pack + Poppler (for pdf2image)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-heb \
        poppler-utils \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy source (Windows binaries are excluded via .dockerignore)
COPY . .

# Ensure output directory exists at runtime
RUN mkdir -p /app/output

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["python", "main.py"]
