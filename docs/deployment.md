# Deployment Guide

## Status

**No live deployment of NeuroFlow exists as a result of this project.**
This is a genuine, followable Railway deployment guide, but it has not
been executed — there is no cloud account, no live URL, no production
data. Fabricating a "live URL" or check results here would misrepresent
the system as deployed when it isn't.

## Target: Railway

Chosen for native multi-service support, Docker-based deploys matching
this repo's existing Dockerfiles, and managed Postgres/Redis.

## Steps

1. `railway init`
2. **Postgres + pgvector**: Railway's one-click Postgres lacks pgvector —
   deploy `pgvector/pgvector:pg16` as a custom Docker Image service
   instead, with a persistent volume at `/var/lib/postgresql/data`.
3. **Redis**: Railway's built-in Redis template is fine (no extension needed).
4. **MLflow**: deploy `ghcr.io/mlflow/mlflow:latest`, backend-store-uri
   pointing at a second logical database on the same Postgres instance.
5. **API**: `railway up --service api --dockerfile backend/Dockerfile`.
   Set every variable from `.env.example`.
6. **Worker**: same image, override start command to `python -m worker`.
7. **Frontend**: `railway up --service frontend --dockerfile frontend/Dockerfile`,
   set `NEXT_PUBLIC_API_BASE_URL` to the API's public URL.
8. **Jaeger + Prometheus** (optional): `jaegertracing/all-in-one` and
   `prom/prometheus`, mounting `infra/prometheus/*.yml`.
9. `infra/init/*.sql` auto-applies only on a FRESH Postgres volume — apply
   manually via `psql` in numeric order if pointing at an existing DB.

## Production verification checklist (run after deploying — not executed here)

1. `GET https://<app>.railway.app/health` → `"status": "ok"`
2. `POST /ingest` with `tests/fixtures/test_doc.pdf` → poll until `complete`
3. `POST /query` → non-empty, cited generation
4. `GET /runs/{run_id}` → evaluation scores present
5. `GET /query/{run_id}/stream` → tokens arrive progressively
6. MLflow URL → experiment visible
7. `GET /metrics` → all custom metrics present
8. `locust -f tests/performance/locustfile.py -H <url> --headless -u 10 -r 2 --run-time 2m`

## Rollback

1. Redeploy the previous `ghcr.io/<repo>/api:<sha>` tag (Railway dashboard
   → Deployments → prior successful deploy → Redeploy).
2. All migrations in `infra/init/` are additive (`ADD COLUMN IF NOT
   EXISTS`) — no reverse migration is needed for a code rollback.
3. Re-run checklist items 1–3 above against the rolled-back deployment.
