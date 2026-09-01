"""Phase 1.2 gate: 37 docs -> 40-55 chunks, unique ids, non-empty content."""

from __future__ import annotations

import pytest

from src.config import DATA_DIR
from src.ingest.chunk import (
    SPLIT_THRESHOLD_TOKENS,
    Chunk,
    chunk_corpus,
    chunk_document,
    corpus_files,
    estimate_tokens,
)

CHUNKS = chunk_corpus()
CORPUS_RELPATHS = {p.relative_to(DATA_DIR).as_posix() for p in corpus_files()}


# --------------------------------------------------------------------------- #
# Gate
# --------------------------------------------------------------------------- #
def test_corpus_has_37_documents() -> None:
    assert len(CORPUS_RELPATHS) == 37


def test_chunk_count_in_gate_band() -> None:
    assert 40 <= len(CHUNKS) <= 55


def test_chunk_ids_unique() -> None:
    ids = [c.chunk_id for c in CHUNKS]
    assert len(ids) == len(set(ids))


def test_chunk_content_non_empty() -> None:
    assert all(c.content.strip() for c in CHUNKS)
    assert all(len(c.content) >= 20 for c in CHUNKS)


def test_spec_docs_and_benchmark_excluded() -> None:
    docs = {c.document for c in CHUNKS}
    assert not any(d.endswith(("ONTOLOGY.md", "SCHEMA.md", "README.md")) for d in docs)
    assert not any("benchmark/" in d for d in docs)


# --------------------------------------------------------------------------- #
# chunk_id shape
# --------------------------------------------------------------------------- #
def test_every_document_is_a_real_corpus_file() -> None:
    assert {c.document for c in CHUNKS} <= CORPUS_RELPATHS


def test_whole_doc_chunk_id_equals_relpath() -> None:
    for chunk in CHUNKS:
        if "#" not in chunk.chunk_id:
            assert chunk.chunk_id == chunk.document


def test_split_chunk_id_is_relpath_hash_slug() -> None:
    split = [c for c in CHUNKS if "#" in c.chunk_id]
    assert split, "expected at least one document to split"
    for chunk in split:
        relpath, _, slug = chunk.chunk_id.partition("#")
        assert relpath == chunk.document
        assert slug and slug == slug.lower()
        assert " " not in slug


# --------------------------------------------------------------------------- #
# Split behaviour on specific docs
# --------------------------------------------------------------------------- #
def test_small_doc_is_one_chunk() -> None:
    chunks = chunk_document(DATA_DIR / "libraries" / "java.md")
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "libraries/java.md"


def test_large_doc_splits_and_covers_all_sections() -> None:
    path = DATA_DIR / "services" / "billing-service.md"
    chunks = chunk_document(path)
    assert len(chunks) > 1
    assert all(c.chunk_id.startswith("services/billing-service.md#") for c in chunks)

    original_headings = [
        ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.startswith("## ")
    ]
    recombined = "\n\n".join(c.content for c in chunks)
    for heading in original_headings:
        assert heading in recombined


def test_no_chunk_greatly_exceeds_threshold() -> None:
    # whole-doc chunks can reach the threshold; nothing should blow well past it.
    assert all(estimate_tokens(c.content) <= SPLIT_THRESHOLD_TOKENS + 40 for c in CHUNKS)


# --------------------------------------------------------------------------- #
# estimate_tokens
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("text", "expected"),
    [("", 0), ("a" * 4, 1), ("a" * 400, 100)],
)
def test_estimate_tokens(text: str, expected: int) -> None:
    assert estimate_tokens(text) == expected


def test_chunk_model_rejects_empty_content() -> None:
    with pytest.raises(ValueError):
        Chunk(chunk_id="x", document="x.md", content="")
