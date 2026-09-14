# Multi-stage, hardened production image.
#
# Build context is the REPO ROOT, not backend/ (see infra/docker-compose.yml
# and infra/docker-compose.prod.yml — both set context: .. for the api/worker
# services), because this app spans backend/, pipelines/, and evaluation/,
# with infra/init/*.sql needed by migrations.py's fallback path. The task's
# reference Dockerfile assumes a backend/-only context; adapted here so the
# image actually contains the code it needs to run.
#
# Two runtime-vs-hardening tradeoffs worth calling out explicitly:
#   - tesseract-ocr is kept in the runtime stage (not stripped as a "build
#     tool") because pipelines/ingestion/extractors/pdf_extractor.py and
#     image_extractor.py call pytesseract at REQUEST TIME, not build time —
#     dropping it wouldn't harden the image, it would silently break OCR.
#   - curl is added solely so the HEALTHCHECK directive below can call
#     GET /health the same way an external prober would; python:3.12-slim
#     doesn't ship it.
# Everything build-only (build-essential, pip's compiler toolchain) stays
# confined to the `deps` stage and never reaches the runtime image.

# ── Stage 1: dependencies (build-only tools live here, never copied forward) ──
FROM python:3.12-slim AS deps
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: runtime (minimal, non-root) ──────────────────────────────
FROM python:3.12-slim AS runtime

RUN groupadd -r neuroflow && useradd -r -g neuroflow neuroflow

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=deps /install /usr/local
COPY . /app

RUN mkdir -p /app/uploads /app/training_data \
    && chown -R neuroflow:neuroflow /app

USER neuroflow

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
