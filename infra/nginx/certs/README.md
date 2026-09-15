# infra/nginx/certs/

This directory holds the TLS certificate/key `nginx` uses in
`infra/docker-compose.prod.yml` (`location listen 443 ssl` in
`infra/nginx/nginx.conf`, expecting `dev.crt` / `dev.key` here). It's mounted
read-only into the `nginx` container: `./nginx/certs:/etc/nginx/certs:ro`.

## Why this directory is empty in version control

A self-signed `dev.crt`/`dev.key` pair was previously committed directly to
this repository. That's a real problem even for a self-signed, localhost-only
dev certificate: private keys don't belong in version control, and
`detect-secrets` (see `.github/workflows/ci.yml`'s `security` job) will flag
an unbaselined key on every run. `*.key` and `infra/nginx/certs/*.crt` are now
gitignored (see root `.gitignore`) - generate your own locally instead.

**This repository's git history still contains the previously-committed key**
(removing a file from the working tree doesn't remove it from prior commits).
If that key was ever used anywhere real, rotate it; if you need it purged
from history entirely, that requires a history rewrite
(`git filter-repo`/BFG) - deliberately not done as part of this change, since
rewriting shared history has its own risks and should be a separate,
intentional decision by whoever owns this repo's remotes.

## Generating a local dev certificate

```bash
cd infra/nginx/certs
openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout dev.key -out dev.crt \
  -days 365 \
  -subj "/CN=localhost"
```

This reproduces the same self-signed, `CN=localhost`, RSA-2048 shape the
previous committed cert had - `nginx.conf` and `docker-compose.prod.yml`
don't need any changes. Your browser will show a certificate warning for this
self-signed cert; that's expected for local development.

## Production

Do not use a self-signed dev cert in production. Supply a real
certificate/key from your CA (or e.g. Let's Encrypt / your cloud provider's
managed TLS) via the same mount point - either by placing the real files here
on the deployment host (outside version control) or, better, via your
orchestrator's secret-mounting mechanism if you're not deploying with this
compose file directly. `docs/runbook.md` Section 6 covers this at a high
level; the exact mechanism depends on where you're actually deploying, which
this repository doesn't currently specify.
