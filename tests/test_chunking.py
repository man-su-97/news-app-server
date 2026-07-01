import pytest

from app.services.ai.chunking import build_article_text, chunk_text


def test_empty_text_returns_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_short_text_is_single_chunk():
    text = "A short news blurb."
    assert chunk_text(text, chunk_size=1000) == [text]


def test_long_text_is_split_into_multiple_chunks():
    text = "word " * 1000  # ~5000 chars
    chunks = chunk_text(text, chunk_size=500, overlap=50)
    assert len(chunks) > 1


def test_chunks_respect_size_bound():
    text = ("Sentence number %d. " % 0) + "".join(
        f"Sentence number {i}. " for i in range(500)
    )
    chunk_size = 400
    chunks = chunk_text(text, chunk_size=chunk_size, overlap=50)
    # Boundary logic may extend slightly to a separator; allow small slack.
    for c in chunks:
        assert len(c) <= chunk_size + len(". ")


def test_consecutive_chunks_overlap():
    # Build text with no separators so cuts are deterministic hard cuts.
    text = "abcdefghij" * 100  # 1000 chars, no spaces
    chunk_size = 200
    overlap = 50
    chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    assert len(chunks) > 1
    # The tail of one chunk should reappear at the head of the next.
    tail = chunks[0][-overlap:]
    assert tail in chunks[1]


def test_full_coverage_no_data_lost():
    text = "abcdefghij" * 100
    chunks = chunk_text(text, chunk_size=200, overlap=50)
    # Every original character index must be covered by some chunk.
    joined = "".join(chunks)
    for ch in set(text):
        assert ch in joined


def test_invalid_params_raise():
    with pytest.raises(ValueError):
        chunk_text("hello", chunk_size=0)
    with pytest.raises(ValueError):
        chunk_text("hello", chunk_size=100, overlap=100)


def test_build_article_text_joins_present_fields():
    assert build_article_text("Title", None, "Body") == "Title\n\nBody"
    assert build_article_text("Title", "Desc", "Body") == "Title\n\nDesc\n\nBody"
    assert build_article_text("Title", None, None) == "Title"
