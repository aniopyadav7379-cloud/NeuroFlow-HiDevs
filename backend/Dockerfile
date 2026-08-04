# Build context is the repo root (see infra/docker-compose.yml:
# api/worker build.context = ".."), because this image needs backend/,
# pipelines/, and infra/ (migrations.py falls back to applying
# infra/init/*.sql itself if it ever runs against a DB that didn't go
# through the postgres service's docker-entrypoint-initdb.d).

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY . /app

RUN mkdir -p /app/uploads

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
