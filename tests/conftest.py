"""
Shared pytest fixtures for tests/integration/*. These tests need a
RUNNING NeuroFlow instance (API + Postgres + Redis + a real or mocked LLM
provider) — they are not runnable in an environment with none of that,
which is why they're written as httpx.AsyncClient integration tests
against a base URL, not unit tests with everything mocked.
"""
import os

import pytest
import pytest_asyncio
from httpx import AsyncClient

BASE_URL = os.environ.get("NEUROFLOW_TEST_BASE_URL", "http://localhost:8000")


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(base_url=BASE_URL, timeout=30.0) as c:
        yield c


@pytest_asyncio.fixture
async def auth_headers(client):
    """Obtains a real token from the running instance's /auth/token using
    test credentials — set NEUROFLOW_TEST_CLIENT_ID/SECRET, or these
    tests will fail auth at the first authenticated call (by design: no
    hardcoded bypass of the auth layer just to make tests pass)."""
    client_id = os.environ.get("NEUROFLOW_TEST_CLIENT_ID", "demo-client")
    client_secret = os.environ.get("NEUROFLOW_TEST_CLIENT_SECRET", "change-me")
    resp = await client.post("/auth/token", json={"client_id": client_id, "client_secret": client_secret})
    resp.raise_for_status()
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def test_pdf_path():
    return "tests/fixtures/test_doc.pdf"
