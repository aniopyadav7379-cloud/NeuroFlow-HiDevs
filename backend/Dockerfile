# Stage 1: Dependencies
FROM python:3.11-slim AS deps
WORKDIR /app
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt .
RUN pip install --upgrade pip wheel setuptools && \
    pip install --default-timeout=100 --no-cache-dir -r requirements.txt

# Stage 2: Runtime (minimal, non-root)
FROM python:3.11-slim AS runtime
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libmagic1 \
    docker.io \
    curl \
    && rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir --upgrade pip wheel setuptools

RUN groupadd -r neuroflow && useradd -r -g neuroflow neuroflow
WORKDIR /app

COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

COPY backend/ /app/backend/
COPY pipelines/ /app/pipelines/
COPY evaluation/ /app/evaluation/
COPY infra/ /app/infra/

# Ensure uploads directory exists and is owned by neuroflow so volume mounts inherit permissions
RUN mkdir -p /app/uploads && chown -R neuroflow:neuroflow /app

USER neuroflow
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
