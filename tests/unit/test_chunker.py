import pytest
import sys
from unittest.mock import AsyncMock, MagicMock

sys.modules['trafilatura'] = MagicMock()

from pipelines.ingestion.chunker import Chunker, ExtractedPage
from backend.providers.client import NeuroFlowClient


def test_chunk_document_empty():
    chunker = Chunker()
    # Need to run async method
    import asyncio
    chunks = asyncio.run(chunker.chunk_document([], "pdf"))
    assert len(chunks) == 0


def test_chunk_fixed_size():
    chunker = Chunker()
    page1 = ExtractedPage(
        content="This is a test sentence. " * 50,
        page_number=1,
        content_type="text",
        metadata={}
    )
    import asyncio
    chunks = asyncio.run(chunker.chunk_document([page1], "txt"))
    assert len(chunks) > 0
    assert chunks[0].metadata["strategy"] == "fixed_size"
    assert chunks[0].chunk_index == 0


def test_chunk_hierarchical():
    chunker = Chunker()
    page1 = ExtractedPage(
        content="Heading 1",
        page_number=1,
        content_type="text",
        metadata={"level": "h1", "section": "Section 1"}
    )
    page2 = ExtractedPage(
        content="Paragraph under heading",
        page_number=2,
        content_type="text",
        metadata={"level": "p", "section": "Section 1"}
    )
    import asyncio
    chunks = asyncio.run(chunker.chunk_document([page1, page2], "pdf"))
    assert len(chunks) == 2
    assert chunks[0].metadata["strategy"] == "hierarchical"
    assert chunks[0].metadata["level"] == "h1"
    assert chunks[1].metadata["parent_section"] == "Section 1"


@pytest.mark.asyncio
async def test_chunk_semantic():
    mock_client = AsyncMock(spec=NeuroFlowClient)
    # Return embeddings for 3 sentences
    mock_client.embed.return_value = [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
    
    chunker = Chunker(client=mock_client)
    page1 = ExtractedPage(
        content="This is sentence one. This is sentence two. This is totally different.",
        page_number=1,
        content_type="text",
        metadata={}
    )
    # We pass 51 pages to trigger semantic chunking in _chunk_document if source_type == pdf
    # Wait, it's easier to just call _chunk_semantic directly
    chunks = await chunker._chunk_semantic([page1])
    assert len(chunks) == 2
    assert chunks[0].metadata["strategy"] == "semantic"
    # Sentence 1 and 2 are grouped (cosine sim 1.0)
    assert "sentence one" in chunks[0].content
    assert "totally different" in chunks[1].content


def test_split_into_sentences_table():
    chunker = Chunker()
    table_content = "Row 1 Col 1 | Row 1 Col 2\nRow 2 Col 1 | Row 2 Col 2"
    sentences = chunker._split_into_sentences(table_content, is_table=True)
    assert len(sentences) == 2
    assert sentences[0] == "Row 1 Col 1 | Row 1 Col 2"
    assert sentences[1] == "Row 2 Col 1 | Row 2 Col 2"
