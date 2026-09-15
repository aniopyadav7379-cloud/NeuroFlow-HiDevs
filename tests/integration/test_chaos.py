import pytest
import asyncio
import httpx
import subprocess
import time
import logging

logger = logging.getLogger(__name__)

REDIS_CONTAINER = "infra-redis-1"
WORKER_CONTAINER = "infra-worker-1"
API_URL = "http://localhost:8000"

def get_container_id(name):
    try:
        result = subprocess.run(["docker", "ps", "-q", "-f", f"name={name}"], capture_output=True, text=True)
        return result.stdout.strip()
    except Exception as e:
        logger.error(f"Failed to get container ID for {name}: {e}")
        return None

def stop_container(name):
    logger.info(f"Killing container {name}...")
    subprocess.run(["docker", "kill", name], check=True)
    time.sleep(2)

def start_container(name):
    logger.info(f"Starting container {name}...")
    subprocess.run(["docker", "start", name], check=True)
    time.sleep(5)

@pytest.mark.asyncio
async def test_redis_chaos_degrades_gracefully():
    # 1. Verify system is healthy initially
    async with httpx.AsyncClient(base_url=API_URL) as client:
        res = await client.get("/health")
        if res.status_code != 200:
            pytest.skip("API is not running on localhost:8000")
            
        redis_id = get_container_id(REDIS_CONTAINER)
        if not redis_id:
            pytest.skip(f"{REDIS_CONTAINER} is not running")
        
        try:
            # 2. Start spamming queries to simulate mid-test activity
            import asyncio
            async def spam_queries():
                errors = 0
                for _ in range(20):
                    try:
                        await client.post("/query", json={"query": "hello", "pipeline_id": "test-pipeline"})
                    except Exception:
                        errors += 1
                    await asyncio.sleep(0.2)
                return errors
                
            spam_task = asyncio.create_task(spam_queries())
            await asyncio.sleep(1) # Let queries start hitting
            
            # 3. Kill Redis MID-TEST
            stop_container(REDIS_CONTAINER)
            
            # 4. Verify system degrades gracefully (does not crash)
            res = await client.get("/health")
            assert res.status_code == 200
            
            # Even without Redis, the core API should stay up
            logger.info(f"Health after Redis kill: {res.json()}")
            
            # Wait for spam to finish
            await spam_task
            
        finally:
            # 5. Restore Redis
            start_container(REDIS_CONTAINER)
            
        # 5. Verify full recovery
        res = await client.get("/health")
        assert res.status_code == 200

@pytest.mark.asyncio
async def test_worker_chaos_requeues_jobs():
    worker_id = get_container_id(WORKER_CONTAINER)
    if not worker_id:
        pytest.skip(f"{WORKER_CONTAINER} is not running")
        
    async with httpx.AsyncClient(base_url=API_URL) as client:
        res = await client.post("/auth/token", json={"client_id": "admin", "client_secret": "test"})
        token = res.json().get("access_token") if res.status_code == 200 else None
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        
        try:
            # 1. Submit ingestion job
            with open("tests/fixtures/test_doc.pdf", "rb") as f:
                res = await client.post("/ingest", files={"file": ("test_doc.pdf", f, "application/pdf")}, headers=headers)
                assert res.status_code == 200
                doc_id = res.json()["document_id"]
            
            # 2. Wait for it to enter 'processing' phase
            entered_processing = False
            for _ in range(10):
                res = await client.get(f"/ingest/{doc_id}", headers=headers)
                if res.json()["status"] == "processing":
                    entered_processing = True
                    break
                await asyncio.sleep(0.5)
                
            if not entered_processing:
                logger.warning("Job finished too fast or didn't start processing in time.")
            
            # 3. Kill worker MID-PROCESSING
            stop_container(WORKER_CONTAINER)
            
            # 4. Verify status is still processing or pending (interrupted)
            res = await client.get(f"/ingest/{doc_id}", headers=headers)
            assert res.json()["status"] in ["pending", "processing"]
            
        finally:
            # 4. Restart worker
            start_container(WORKER_CONTAINER)
            
        # 5. Verify job eventually completes (ARQ re-queues or picks it up)
        start_time = time.time()
        completed = False
        while time.time() - start_time < 45:
            res = await client.get(f"/ingest/{doc_id}", headers=headers)
            if res.status_code == 200 and res.json()["status"] == "complete":
                completed = True
                break
            await asyncio.sleep(2)
            
        assert completed, f"Job {doc_id} did not recover and complete after worker restart!"
