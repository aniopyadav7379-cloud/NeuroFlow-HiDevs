# NeuroFlow: Project Retrospective

This retrospective covers the state of the project through the end of this
audit (working branch `task-49`, pending Task 20 finalization on `task-50`).
It is written to be read on its own; where a claim depends on something this
audit couldn't verify, that's stated explicitly rather than implied.

## Architecture decisions

The system splits cleanly into five subsystems - ingestion, retrieval,
generation, evaluation, and fine-tuning - communicating through PostgreSQL
(with pgvector for embeddings) and Redis (job queue via ARQ, caching, rate
limiting, circuit-breaker state). The FastAPI process and the ARQ worker
process are separate so a slow/failing ingestion job can't block API
responsiveness. Untrusted file parsing (PDF/DOCX/image OCR from user
uploads) runs in a sandboxed sibling Docker container rather than in-process,
trading a documented Docker-socket-access risk for isolation of a genuinely
higher-risk operation (parsing attacker-controlled files with libraries that
have a real history of RCE-class bugs). See `docs/architecture.md` for
subsystem-level diagrams and `docs/adr/` (referenced there) for the specific
technology choices.

## Major issue found: evaluation fabrication

The most significant finding of this audit was in Task 18's quality-
improvement work. Three independent code paths were generating evaluation
scores with `random.uniform()` instead of calling the real LLM judge:

1. **`backend/api/evaluations.py::process_evaluation_queue`** - the actual
   production Redis-queue consumer that populates the live `evaluations`
   table and dashboard, not a test-only path.
2. **`evaluation/generation_eval.py::run_variant_eval`** - the A/B prompt
   comparison, with Variant B's random range hardcoded higher than Variant
   A's, guaranteeing it would "win" regardless of what either prompt
   actually produced.
3. **`evaluation/hyperparameter_search.py`** - retrieval MRR from a
   hand-tuned formula plus jitter, explicitly commented as simulating to
   avoid real API calls.

All three now call genuine per-metric LLM-as-judge logic
(`evaluation/judge.py`, `evaluation/metrics/`), verified by real code
execution (imports succeed with full dependencies installed, `ruff`/`mypy`
clean) - not just read and assumed correct. `evaluation/improvement_log.md`
was rewritten to state plainly that the previously-claimed 0.72→0.81 /
0.68→0.79 / 0.65→0.76 improvement numbers were fabricated, and that
`quality_baseline.json`, `quality_final.json`, and `best_retrieval_config.json`
predate the fix and are stale until regenerated against a live DB + LLM
provider - which this audit environment did not have. **No replacement
numbers were invented.** The one legitimate use of `random.uniform()`
remaining in the codebase, `/evaluations/simulate`, is explicitly documented
as a synthetic-data endpoint for dashboard testing and never writes to the
real `evaluations` table.

## Other reliability bugs found and fixed

None of these were visible from reading code in isolation - each was
confirmed by tracing a real interaction between two parts of the system, or
by actually running the relevant code/tests:

- **Worker never listened on the queue jobs were enqueued to.**
  `backend/worker.py`'s `WorkerSettings` never set `queue_name`, defaulting
  to ARQ's own `"arq:queue"`, while `backend/api/ingest.py` enqueues to
  `"queue:ingest"`. Ingestion would have silently accepted uploads and never
  processed them - no error, just permanently `queued` documents. Confirmed
  by reading ARQ's `enqueue_job`/`create_worker` source, not guesswork.
- **Health check and backpressure both used the wrong Redis data type.**
  ARQ stores queued jobs in a sorted set (`ZADD`); `LLEN` (list length)
  against that key raises `WRONGTYPE` in real Redis. In `/health` this was
  silently swallowed by a blanket exception handler, masking circuit-breaker
  status along with it; in the backpressure check
  (`backend/resilience/backpressure.py`) it would have thrown on every
  ingest request once any real job had ever been queued.
- **`/health` reported a hardcoded fake worker count.** `workers if workers
  else 2` meant `/health` claimed 2 healthy workers even when zero were
  running, because the underlying check was also querying a Redis key ARQ
  never populates in this version. Rebuilt around ARQ's real TTL'd
  health-check key.
- **Streaming responses could get stuck at `status='running'` forever.**
  `StreamingGenerator.generate_stream()` had no cleanup path for a client
  disconnecting mid-stream (`GeneratorExit`). Added `try/except` covering the
  full stream body so an aborted or failed run is marked `'failed'`; verified
  with a new regression test that actually calls `aclose()` mid-stream and
  asserts the DB update fires, plus a second test confirming normal
  completion is unaffected.
- **SDK gaps**: unbounded polling (no timeout) on ingestion/evaluation
  status checks; retries only handled `429`, not the `503` the backend's own
  backpressure mechanism returns; `Retry-After`/body `retry_after` were
  ignored in favor of blind exponential backoff; no async context-manager
  support. All fixed and covered by new unit tests (pure in-memory,
  no live infra needed).
- **Two broken SDK-facing examples**, both reproduced, not just inferred:
  `async for token in client.query(..., stream=True)` without `await` raises
  `TypeError` (query() is a coroutine returning a generator, not a generator
  itself) - present in both `sdk/README.md` and `sdk/examples/quickstart.py`.
  The quickstart also called `logger.info(..., end="", flush=True)`, which
  either prints nothing (unconfigured logging) or raises `TypeError`
  (configured logging) - both failure modes reproduced directly.
- **CI configuration**: the `security` job's `git diff --name-only HEAD~1`
  fails on every run under `actions/checkout@v4`'s default shallow clone
  (reproduced generically); `quality-gate.yml` passed `--env staging` to a
  script with no argument parsing at all, so it silently ignored the flag and
  would have failed on an unresolvable docker-compose hostname rather than
  ever reaching a real check.
- **Missing dependencies**: `structlog` and `apscheduler`, both imported by
  `backend/db/retention.py`, were absent from `backend/requirements.txt` -
  confirmed via real `ModuleNotFoundError` on a clean install.
- **A private key was committed** (`infra/nginx/certs/dev.key`). Removed
  from the working tree, gitignored going forward, with a documented
  `openssl` command (verified to reproduce an equivalent cert) replacing it.
  This does not purge it from git history - that would require a history
  rewrite, deliberately out of scope here per this audit's git restrictions,
  and is a decision for whoever owns this repo's remotes.

## Testing improvements

Added `tests/unit/test_sdk_client.py` (8 tests: retry-delay logic, polling
timeouts, async context manager) and
`tests/unit/test_generator_streaming_cleanup.py` (2 tests: abort-triggers-
failed, completion-still-succeeds) - all targeting the specific bugs found
above, not generic coverage padding. Full unit suite: **32 passed, 0
failed** (one pre-existing file, `test_chunker.py`, excluded due to a sandbox
network restriction unrelated to this audit's changes).

## What remains genuinely unverified

This environment had no live PostgreSQL, Redis, Docker, or LLM provider
access, and blocked network access to `fonts.googleapis.com` and
`openaipublic.blob.core.windows.net`. As a direct result, the following are
**verified by code reading and reproduction of the specific failure
conditions, but not by an actual live run**:

- End-to-end ingestion (upload → worker processes → document reaches
  `status='complete'`) with the queue-name fix in place.
- `/health`'s real output under live Redis (`ZCARD`/health-check-key logic
  is correct per ARQ's source, but unobserved against a running worker).
- `tests/integration/` (8 tests) - infra-gated, not genuine code failures.
- Frontend production build (`next/font/google` needs network access this
  sandbox doesn't have; not a code issue - build succeeded through `npm
  install`).
- `tests/unit/test_chunker.py` (tiktoken vocabulary download blocked).
- Regenerated evaluation numbers post-fabrication-fix (needs live DB + LLM
  provider - genuinely can't be done without them, and no numbers were
  invented to fill the gap).
- Any live deployment status (a "Live API Production URL" previously in the
  root README could not be confirmed reachable from this environment and was
  removed from that claim rather than left unverified-but-stated).

## Lessons learned

The fabricated-evaluation issue is the clearest illustration of why "it ran
without errors" isn't the same as "it's correct" - `random.uniform()` calls
produce plausible-looking floats in a sane range, pass every type check, and
would sail through a superficial review. What caught it was reading what the
numbers were actually derived from, not just that numbers existed. The
queue-name mismatch and the `LLEN`-vs-sorted-set bug are the same shape of
problem one level down: each individual piece (the enqueue call, the
`WorkerSettings` class, the health check) was internally consistent and
plausible on its own; only tracing the actual data flow between them
surfaced the mismatch. Where this audit found a real bug, it was fixed and
verified by running something real (a test, a lint pass, a mypy check, an
actual reproduction of the failure) rather than by reasoning alone - and
where genuine verification wasn't possible in this environment, that's
stated as such rather than assumed.
