"""Phase 3.3: vector retriever.

Unit tests use a fake PGVector (no Postgres). The ``pgvector`` gate test hits the
live ``meridian_chunks`` collection and enforces B01-B08 top-3 recall.
"""

from __future__ import annotations

import pytest
from langchain_core.documents import Document

from scripts.eval_vector_retrieval import check, load_eval_set
from src.config import REPO_ROOT
from src.pipeline.retrieve_vector import DEFAULT_K, retrieve_vector


class FakeStore:
    """Returns canned (Document, distance) pairs; records the k it was asked for."""

    def __init__(self, hits: list[tuple[Document, float]]) -> None:
        self.hits = hits
        self.last_k: int | None = None

    def similarity_search_with_score(
        self, _query: str, k: int = 4
    ) -> list[tuple[Document, float]]:
        self.last_k = k
        return self.hits[:k]


def _doc(chunk_id: str, document: str = "", content: str = "text") -> Document:
    return Document(
        page_content=content,
        metadata={"chunk_id": chunk_id, "document": document or chunk_id},
    )


# --------------------------------------------------------------------------- #
# unit (fake store)
# --------------------------------------------------------------------------- #
def test_maps_documents_to_passages_preserving_order() -> None:
    store = FakeStore([(_doc("a.md"), 0.1), (_doc("b.md"), 0.4)])
    passages = retrieve_vector("q", store=store)
    assert [p.chunk_id for p in passages] == ["a.md", "b.md"]
    assert passages[0].score == 0.1
    assert passages[0].content == "text"


def test_passes_k_through_to_the_store() -> None:
    store = FakeStore([(_doc(f"{i}.md"), 0.1 * i) for i in range(10)])
    retrieve_vector("q", k=3, store=store)
    assert store.last_k == 3


def test_default_k_is_used_when_unspecified() -> None:
    store = FakeStore([(_doc(f"{i}.md"), 0.1) for i in range(10)])
    retrieve_vector("q", store=store)
    assert store.last_k == DEFAULT_K


def test_empty_result_is_not_an_error() -> None:
    assert retrieve_vector("q", store=FakeStore([])) == []


def test_document_falls_back_to_chunk_id_when_metadata_missing() -> None:
    doc = Document(page_content="x", metadata={"chunk_id": "only-id.md"})
    passages = retrieve_vector("q", store=FakeStore([(doc, 0.2)]))
    assert passages[0].document == "only-id.md"


# --------------------------------------------------------------------------- #
# fixture hygiene
# --------------------------------------------------------------------------- #
def test_gate_fixture_tracks_the_benchmark_vector_set() -> None:
    questions, _, _ = load_eval_set()
    assert {q["benchmark_ref"] for q in questions} == {
        "B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08"
    }
    benchmark = (REPO_ROOT / "data" / "benchmark" / "questions.md").read_text("utf-8")
    for item in questions:
        assert f"**{item['benchmark_ref']}." in benchmark


# --------------------------------------------------------------------------- #
# GATE — live pgvector
# --------------------------------------------------------------------------- #
@pytest.mark.pgvector
def test_vector_retrieval_gate() -> None:
    questions, rank_within, k = load_eval_set()
    cases = [check(item, rank_within=rank_within, k=k) for item in questions]
    failed = [(c.question, c.detail) for c in cases if not c.ok]
    assert not failed, f"below top-{rank_within}: {failed}"
