import sys
sys.path.insert(0, ".")
import pytest
import pipelines.ingestion.chunker as chunker_mod

class _FakeEncoding:
    def encode(self, text): return text.split(" ") if text else []
    def decode(self, tokens): return " ".join(tokens)

@pytest.fixture(autouse=True)
def _patch_encoding(monkeypatch):
    monkeypatch.setattr(chunker_mod, "_get_encoding", lambda: _FakeEncoding())

def test_fixed_size_never_splits_mid_sentence():
    text = ("The quick brown fox jumps over the lazy dog. " * 40) + "Final sentence here."
    chunks = chunker_mod.chunk_fixed_size(text, {}, chunk_tokens=50, overlap_tokens=10)
    assert len(chunks) > 1
    for c in chunks[:-1]:
        assert c.text.rstrip()[-1] in ".!?"

def test_fixed_size_respects_overlap():
    text = "word " * 200
    chunks = chunker_mod.chunk_fixed_size(text, {}, chunk_tokens=50, overlap_tokens=10)
    assert len(chunks) >= 2
    tail_words = set(chunks[0].text.split()[-5:])
    head_words = set(chunks[1].text.split()[:15])
    assert tail_words & head_words

def test_fixed_size_short_text_single_chunk():
    text = "A short piece of text."
    chunks = chunker_mod.chunk_fixed_size(text, {}, chunk_tokens=512, overlap_tokens=64)
    assert len(chunks) == 1
    assert chunks[0].text == text

def test_select_strategy_table_always_fixed_size():
    from pipelines.ingestion.extractors.base import ExtractedPage
    page = ExtractedPage(1, "a table", "table", {})
    assert chunker_mod.select_strategy(page, source_type="pdf", page_count=100, doc_has_headings=False) == "fixed_size"

def test_select_strategy_docx_headings_hierarchical():
    from pipelines.ingestion.extractors.base import ExtractedPage
    page = ExtractedPage(1, "text", "text", {"level": "h1"})
    assert chunker_mod.select_strategy(page, source_type="docx", page_count=5, doc_has_headings=True) == "hierarchical"

def test_select_strategy_long_pdf_semantic():
    from pipelines.ingestion.extractors.base import ExtractedPage
    page = ExtractedPage(1, "text", "text", {})
    assert chunker_mod.select_strategy(page, source_type="pdf", page_count=80, doc_has_headings=False) == "semantic"

def test_hierarchical_chunking_parent_child_linkage():
    from pipelines.ingestion.extractors.base import ExtractedPage
    pages = [
        ExtractedPage(1, "Introduction", "text", {"level": "h1"}),
        ExtractedPage(2, "Intro body text here.", "text", {}),
        ExtractedPage(3, "Methods", "text", {"level": "h1"}),
        ExtractedPage(4, "Methods body text here.", "text", {}),
    ]
    chunks = chunker_mod.chunk_hierarchical(pages)
    parents = [c for c in chunks if c.metadata["hierarchy_role"] == "parent"]
    children = [c for c in chunks if c.metadata["hierarchy_role"] == "child"]
    assert len(parents) == 2
    assert all(c.metadata["parent_id"] in (1, 2) for c in children)
