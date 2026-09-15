import asyncio
import os

import httpx

API_URL = "http://localhost:8000"


async def test_deduplication() -> None:
    # Create a dummy text file
    with open("dummy.txt", "w") as f:  # noqa: ASYNC230
        f.write("This is a new dummy file 2 for testing deduplication.")

    async with httpx.AsyncClient() as client:
        # First upload
        with open("dummy.txt", "rb") as f:  # noqa: ASYNC230
            files = {"file": ("dummy.txt", f, "text/plain")}
            resp1 = await client.post(f"{API_URL}/ingest", files=files)

        data1 = resp1.json()
        print("First upload:", data1)
        assert data1["duplicate"] == False  # noqa: E712
        assert data1["status"] == "queued"
        doc_id = data1["document_id"]

        # Second upload
        with open("dummy.txt", "rb") as f:  # noqa: ASYNC230
            files = {"file": ("dummy.txt", f, "text/plain")}
            resp2 = await client.post(f"{API_URL}/ingest", files=files)

        data2 = resp2.json()
        print("Second upload:", data2)
        assert data2["duplicate"] == True  # noqa: E712
        assert data2["document_id"] == doc_id

        # Wait for processing
        print("Waiting for processing to complete...")
        for _ in range(10):
            status_resp = await client.get(f"{API_URL}/documents/{doc_id}")
            status_data = status_resp.json()
            print("Status:", status_data["status"])
            if status_data["status"] == "complete":
                print("Processing complete!")
                break
            await asyncio.sleep(2)

    os.remove("dummy.txt")
    print("\n--- Test Deduplication & Worker Pipeline Completed ---")


if __name__ == "__main__":
    asyncio.run(test_deduplication())
