import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import asyncio
from backend.main import app
from backend.db.pool import get_pool
from backend.config import settings
from arq.worker import Worker
from backend.worker import WorkerSettings

@pytest_asyncio.fixture(scope="session")
async def worker_task():
    # Start the ARQ worker in the background for integration tests
    worker = Worker(**WorkerSettings.__dict__)
    task = asyncio.create_task(worker.main())
    # Give it a second to connect
    await asyncio.sleep(1)
    yield
    # Cleanup
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

@pytest_asyncio.fixture(scope="session")
async def async_client(worker_task):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

@pytest_asyncio.fixture(scope="session")
async def admin_token(async_client):
    response = await async_client.post("/auth/token", json={"client_id": "admin", "client_secret": "test"})
    return response.json()["access_token"]

@pytest_asyncio.fixture(scope="session")
async def query_token(async_client):
    response = await async_client.post("/auth/token", json={"client_id": "query_only", "client_secret": "test"})
    return response.json()["access_token"]

@pytest_asyncio.fixture(scope="session")
async def db():
    pool = get_pool()
    yield pool
