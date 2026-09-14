import random
from locust import HttpUser, task, between
SAMPLE_QUERIES = [
    "What is the main topic of the document?",
    "Explain the architecture.",
    "How does the chunker work?",
    "What is NeuroFlow?",
    "Who is the author?"
]

TEST_DOCS = [
    "tests/fixtures/test_doc.pdf"
]

class QueryUser(HttpUser):
    weight = 7
    wait_time = between(1, 3)
    
    def on_start(self):
        # Authenticate
        res = self.client.post("/auth/token", json={"client_id": "query_only", "client_secret": "test"})
        if res.status_code == 200:
            self.token = res.json()["access_token"]
        else:
            self.token = None
            
        # Get a pipeline
        # Since query_only cannot create pipelines, we assume one exists or we just create one as admin in setup
        # For simplicity, we just use a random UUID, but the API will 404 if pipeline doesn't exist
        # Wait, the load test must succeed. We should let AdminUser create a pipeline, or create it here.
        res = self.client.post("/auth/token", json={"client_id": "admin", "client_secret": "test"})
        admin_token = res.json()["access_token"]
        res = self.client.post("/pipelines", json={
            "config": {
                "name": "Load Test Pipeline", "description": "Test",
                "ingestion": {"chunking_strategy": "fixed", "chunk_size_tokens": 512, "chunk_overlap_tokens": 64, "extractors_enabled": []},
                "retrieval": {"dense_k": 5, "sparse_k": 0, "reranker": "none", "top_k_after_rerank": 5, "query_expansion": False, "metadata_filters_enabled": False},
                "generation": {"model_routing": {"task_type": "factual", "max_cost_per_call": 1.0}, "max_context_tokens": 4096, "temperature": 0.0, "system_prompt_variant": "default"},
                "evaluation": {"auto_evaluate": False, "training_threshold": 0.8}
            }
        }, headers={"Authorization": f"Bearer {admin_token}"})
        
        if res.status_code == 200:
            self.pipeline_id = res.json()["id"]
        else:
            self.pipeline_id = "default"

    @task
    def query_pipeline(self):
        if not self.token:
            return
        headers = {"Authorization": f"Bearer {self.token}"}
        self.client.post("/query", json={
            "query": random.choice(SAMPLE_QUERIES),
            "pipeline_id": self.pipeline_id
        }, headers=headers)

class IngestUser(HttpUser):
    weight = 2
    wait_time = between(5, 10)
    
    def on_start(self):
        res = self.client.post("/auth/token", json={"client_id": "admin", "client_secret": "test"})
        if res.status_code == 200:
            self.token = res.json()["access_token"]
        else:
            self.token = None

    @task
    def ingest_document(self):
        if not self.token:
            return
        headers = {"Authorization": f"Bearer {self.token}"}
        doc_path = random.choice(TEST_DOCS)
        with open(doc_path, "rb") as f:
            self.client.post("/ingest", files={"file": (doc_path, f, "application/pdf")}, headers=headers)

class AdminUser(HttpUser):
    weight = 1
    wait_time = between(2, 5)
    
    def on_start(self):
        res = self.client.post("/auth/token", json={"client_id": "admin", "client_secret": "test"})
        if res.status_code == 200:
            self.token = res.json()["access_token"]
        else:
            self.token = None

    @task
    def check_evaluations(self):
        if not self.token:
            return
        headers = {"Authorization": f"Bearer {self.token}"}
        self.client.get("/evaluations", headers=headers)
