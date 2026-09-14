"""
Locust load test. NOT runnable to produce real numbers in this
environment — there's no live NeuroFlow instance with real LLM
credentials here to load-test. Run for real via:

    locust -f tests/performance/locustfile.py --host http://localhost:8000 \
        --users 50 --spawn-rate 5 --run-time 5m --headless \
        --csv tests/performance/load_test_results

See the module-level NOTE at the bottom of this file and the task
response for why tests/performance/load_test_results.json is NOT
committed alongside this file.
"""
import os
import random

from locust import HttpUser, between, task

SAMPLE_QUERIES = [
    "What is HNSW indexing?",
    "How does reciprocal rank fusion work?",
    "Explain the retrieval pipeline architecture.",
    "What are the four evaluation metrics?",
    "How does the circuit breaker recover?",
]

TEST_DOCS = ["tests/fixtures/test_doc.pdf"]

PIPELINE_ID = os.environ.get("NEUROFLOW_TEST_PIPELINE_ID", "")


def _auth_headers(client_id: str = "demo-client", client_secret: str = "change-me") -> dict:
    """Each Locust user process needs its own token — tokens expire
    after 3600s (backend/security/auth.py's TOKEN_EXPIRY_SECONDS), which
    comfortably outlasts a 5-minute load test run."""
    import httpx

    resp = httpx.post(
        f"{os.environ.get('NEUROFLOW_TEST_BASE_URL', 'http://localhost:8000')}/auth/token",
        json={"client_id": client_id, "client_secret": client_secret},
        timeout=10.0,
    )
    resp.raise_for_status()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


class QueryUser(HttpUser):
    weight = 7
    wait_time = between(1, 3)

    def on_start(self):
        self.headers = _auth_headers()

    @task
    def query_pipeline(self):
        self.client.post(
            "/query",
            json={"pipeline_id": PIPELINE_ID, "query": random.choice(SAMPLE_QUERIES), "stream": False},
            headers=self.headers,
            name="/query",
        )


class IngestUser(HttpUser):
    weight = 2
    wait_time = between(2, 5)

    def on_start(self):
        self.headers = _auth_headers()

    @task
    def ingest_document(self):
        with open(random.choice(TEST_DOCS), "rb") as f:
            self.client.post(
                "/ingest",
                files={"file": ("test_doc.pdf", f, "application/pdf")},
                headers=self.headers,
                name="/ingest",
            )


class AdminUser(HttpUser):
    weight = 1
    wait_time = between(3, 8)

    def on_start(self):
        self.headers = _auth_headers()

    @task
    def check_pipelines(self):
        # GET /evaluations doesn't exist as a plain endpoint (Task 41
        # built GET /evaluations/stream, an SSE feed, not a paginated
        # list) — GET /pipelines is the closest equivalent "admin looks
        # at overview data" read this AdminUser type represents.
        self.client.get("/pipelines", headers=self.headers, name="/pipelines")


# NOTE ON load_test_results.json: this task's checklist requires
# committing real results (P95 < 5s, error rate < 2% at 50 concurrent
# users over 5 minutes). That requires a running NeuroFlow instance with
# live LLM provider credentials under real load — neither is available
# in this sandboxed environment (no Docker, no LLM API keys, no way to
# sustain 50 concurrent users against anything). Fabricating a results
# file with invented numbers that happen to clear the bar would misrepresent
# the system as load-tested when it hasn't been. This file is real and
# ready to run; tests/performance/load_test_results.json is not committed
# because doing so honestly requires the run described in this file's
# docstring, which must happen against your actual deployed stack.
