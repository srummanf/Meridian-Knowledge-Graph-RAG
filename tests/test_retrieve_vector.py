"""Phase 3.3 (retriever) + Phase 2.2 (recall sanity check).

Unit tests use a fake PGVector (no Postgres). Two `pgvector` gates:

- **retriever** — B01-B08 (`vector_retrieval_eval.json`) each surface an
  acceptable source chunk in the top 3 against the live `meridian_chunks`.
- **recall** — recall@5 over `vector_eval.json` clears 0.9 (why there is *no* ANN
  index: ~42 vectors, exact scan is sub-ms and recall-1.0 by construction;
  HNSW/IVFFlat only pay off 3-5 orders of magnitude larger and would add
  approximation error).
"""

from __future__ import annotations

import json

import pytest
from langchain_core.documents import Document

from src.config import REPO_ROOT
from src.ingest.chunk import chunk_corpus
from src.pipeline.retrieve_vector import DEFAULT_K, retrieve_vector

RETRIEVER_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "vector_retrieval_eval.json"
RECALL_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "vector_eval.json"


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


def test_passes_k_through_and_defaults_when_unspecified() -> None:
    store = FakeStore([(_doc(f"{i}.md"), 0.1) for i in range(10)])
    retrieve_vector("q", k=3, store=store)
    assert store.last_k == 3
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
def test_retriever_fixture_tracks_the_benchmark_vector_set() -> None:
    questions = json.loads(RETRIEVER_FIXTURE.read_text("utf-8"))["questions"]
    assert {q["benchmark_ref"] for q in questions} == {
        "B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08"
    }
    benchmark = (REPO_ROOT / "data" / "benchmark" / "questions.md").read_text("utf-8")
    for item in questions:
        assert f"**{item['benchmark_ref']}." in benchmark


def test_recall_fixture_gold_ids_are_real_chunks() -> None:
    pairs = json.loads(RECALL_FIXTURE.read_text("utf-8"))["pairs"]
    real = {c.chunk_id for c in chunk_corpus()}
    unknown = [p["gold_chunk_id"] for p in pairs if p["gold_chunk_id"] not in real]
    assert not unknown, f"fixture references missing chunks: {unknown}"
    assert len(pairs) >= 10


# --------------------------------------------------------------------------- #
# GATE — live pgvector
# --------------------------------------------------------------------------- #
@pytest.mark.pgvector
def test_vector_retrieval_gate() -> None:
    data = json.loads(RETRIEVER_FIXTURE.read_text("utf-8"))
    rank_within, k = data.get("rank_within", 3), data.get("k", 5)
    failed = []
    for item in data["questions"]:
        found = [p.chunk_id for p in retrieve_vector(item["question"], k=k)]
        gold = set(item["gold_chunks"])
        ranks = [i + 1 for i, cid in enumerate(found) if cid in gold]
        if not ranks or min(ranks) > rank_within:
            failed.append((item["question"], f"gold {sorted(gold)} not in top-{rank_within}; got {found}"))
    assert not failed, failed


@pytest.mark.pgvector
def test_recall_at_5_clears_the_gate() -> None:
    data = json.loads(RECALL_FIXTURE.read_text("utf-8"))
    pairs, gate = data["pairs"], data.get("recall_at_5_gate", 0.9)

    misses = [
        p["question"]
        for p in pairs
        if p["gold_chunk_id"] not in {r.chunk_id for r in retrieve_vector(p["question"], k=5)}
    ]
    recall_at_5 = 1 - len(misses) / len(pairs)
    assert recall_at_5 >= gate, f"recall@5 {recall_at_5:.2f} < {gate}; missed: {misses}"
