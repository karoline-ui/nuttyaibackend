# ── Stage 1: Build ────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# System deps mínimos para build
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev mupdf-tools ffmpeg curl gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Runtime deps apenas
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev mupdf-tools ffmpeg curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copia deps instalados
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

COPY . .

RUN mkdir -p /app/uploads

# Non-root user — segurança
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Cloud Run usa $PORT dinamicamente
EXPOSE 8080

# WEB_CONCURRENCY=2 por padrão (1 por 512MB RAM)
# Cloud Run: configure WEB_CONCURRENCY=4 para instâncias 2GB+
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --workers ${WEB_CONCURRENCY:-2} --timeout-keep-alive 75 --access-log"]
