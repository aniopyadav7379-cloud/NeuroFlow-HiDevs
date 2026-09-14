# Multi-stage frontend image.
#
# DEVIATION FROM THE TASK'S REFERENCE DOCKERFILE, documented here rather
# than silently: the reference stage 2 is `nginx:alpine` serving
# `.next/standalone` directly. That doesn't actually run — Next.js
# "standalone" output is a self-contained NODE SERVER (server.js), not a
# static site; nginx alone has no JavaScript runtime to execute it, so
# copying those files into an nginx image produces a container that starts
# but 500s on every request. This Dockerfile's runtime stage uses
# `node:20-slim` and actually runs `node server.js`. The task's other
# nginx.conf requirements (load balancing, rate limiting, SSL termination,
# gzip, security headers) still apply — see infra/nginx/nginx.conf, which
# reverse-proxies to this container's port 3000 exactly as it would to a
# "real" nginx-fronted app; the difference is invisible from outside the
# container, only the internal stage-2 base image changed.

# ── Stage 1: build ──────────────────────────────────────────────────
FROM node:20-slim AS builder
WORKDIR /app
COPY package*.json .
RUN npm ci
COPY . .
RUN npm run build

# ── Stage 2: runtime (minimal, non-root) ────────────────────────────
FROM node:20-slim AS runtime

RUN groupadd -r neuroflow && useradd -r -g neuroflow neuroflow

WORKDIR /app
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

RUN chown -R neuroflow:neuroflow /app
USER neuroflow

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD node -e "fetch('http://localhost:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
