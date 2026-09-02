"""Embed each chunk locally and upsert it into pgvector.

The vector half of ingestion (architecture.md §6, §8). Embeddings come from a
local ``bge-small`` model (384-dim, :func:`src.config.embeddings`) — **no API
call** — and are stored through ``langchain_postgres.PGVector``.

The corpus is ~45 vectors, so retrieval is an exact scan: there is no
HNSW/IVFFlat index (Phase 2.2 writes up why an ANN index would be pointless
here). Each chunk is stored under ``id = chunk_id``, so ``add_documents``
replaces rather than appends — the vector load is idempotent, like the graph
load.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from langchain_core.documents import Document
from langchain_postgres import PGVector

from src.config import EMBED_DIM, embeddings, settings
from src.ingest.resolve import resolve_entity
from src.logging_config import get_logger

if TYPE_CHECKING:
    from src.ingest.chunk import Chunk
    from src.models.extraction import ExtractionResult

log = get_logger("load_vector")

COLLECTION_NAME = "meridian_chunks"


def vector_store(
    *,
    connection: str | None = None,
    embedding=None,
    collection: str = COLLECTION_NAME,
) -> PGVector:
    """The project's PGVector handle (cosine distance, 384-dim, exact scan).

    ``collection`` defaults to the corpus collection; the recall eval passes its
    own so it never disturbs the real index.
    """
    return PGVector(
        embeddings=embedding or embeddings(),
        connection=connection or settings.postgres_dsn,
        collection_name=collection,
        embedding_length=EMBED_DIM,
        use_jsonb=True,
    )


def entity_ids_by_chunk(results: list[ExtractionResult]) -> dict[str, list[str]]:
    """``chunk_id -> sorted resolved entity ids mentioned in that chunk``.

    Entities are resolved the same way the graph resolves them, so a vector
    hit's ``entity_ids`` line up with Neo4j node ids for hybrid retrieval
    (Phase 3).
    """
    by_chunk: dict[str, set[str]] = defaultdict(set)
    for result in results:
        for entity in result.entities:
            by_chunk[entity.source_chunk_id].add(resolve_entity(entity).id)
    return {chunk_id: sorted(ids) for chunk_id, ids in by_chunk.items()}


def _documents(
    chunks: list[Chunk], ids_by_chunk: dict[str, list[str]]
) -> list[Document]:
    return [
        Document(
            page_content=chunk.content,
            metadata={
                "chunk_id": chunk.chunk_id,
                "document": chunk.document,
                "entity_ids": ids_by_chunk.get(chunk.chunk_id, []),
            },
        )
        for chunk in chunks
    ]


def load_vector(
    chunks: list[Chunk],
    results: list[ExtractionResult],
    *,
    store: PGVector | None = None,
    wipe_first: bool = False,
) -> dict[str, int]:
    """Embed every chunk and upsert into pgvector. Returns post-load counts."""
    store = store or vector_store()
    if wipe_first:
        store.delete_collection()
        store.create_collection()

    documents = _documents(chunks, entity_ids_by_chunk(results))
    store.add_documents(documents, ids=[chunk.chunk_id for chunk in chunks])
    log.info("embedded %d chunks into '%s'", len(documents), store.collection_name)

    return {"chunks_embedded": len(documents), "dim": EMBED_DIM}
