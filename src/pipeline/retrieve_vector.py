"""Phase 3.3: vector retriever — question -> top-k corpus passages.

The framework half of retrieval (architecture.md §6). One
``PGVector.similarity_search_with_score`` call against the ``meridian_chunks``
collection: exact cosine scan, no HNSW (rules.md §5.3 — the corpus is ~42
vectors, an ANN index would only add approximation error; Phase 2.2 has the
write-up). No LLM call.

The score PGVector returns is a cosine *distance* in ``[0, 2]`` (0 = identical),
and rows arrive already sorted ascending — :class:`Passage.score` keeps that raw
distance so downstream ranking stays in one convention.

An empty result is not an error: it returns ``[]`` and the pipeline routes the
question to REFUSE (rules.md §2.4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.ingest.load_vector import vector_store
from src.logging_config import get_logger
from src.models.answer import Passage

if TYPE_CHECKING:
    from langchain_core.documents import Document
    from langchain_postgres import PGVector

log = get_logger("retrieve_vector")

DEFAULT_K = 5  # rules.md §5.3: "k small"


def _passage(document: Document, score: float) -> Passage:
    meta = document.metadata
    return Passage(
        chunk_id=meta["chunk_id"],
        document=meta.get("document") or meta["chunk_id"],
        content=document.page_content,
        score=float(score),
    )


def retrieve_vector(
    question: str, *, k: int = DEFAULT_K, store: PGVector | None = None
) -> list[Passage]:
    """Top-``k`` passages for ``question`` by exact cosine similarity.

    ``store`` is injectable for tests; production uses the shared
    ``meridian_chunks`` handle. Rows come back sorted nearest-first.
    """
    store = store or vector_store()
    hits = store.similarity_search_with_score(question, k=k)
    passages = [_passage(doc, score) for doc, score in hits]

    log.info(
        "route vector: %r -> %d passages %s",
        question,
        len(passages),
        [p.chunk_id for p in passages],
    )
    return passages
