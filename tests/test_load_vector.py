"""Phase 2.1: chunk -> local embedding -> pgvector.

Unit tests (no DB) cover the metadata shaping and the chunk->entity-id map. The
``pgvector``-marked test is the gate: a real embed + upsert, idempotent, and a
similarity search that returns the right chunk with 384-dim vectors.
"""

from __future__ import annotations

import pytest

from src.ingest.chunk import Chunk
from src.ingest.load_vector import (
    COLLECTION_NAME,
    _documents,
    entity_ids_by_chunk,
    load_vector,
    vector_store,
)
from src.models.extraction import ExtractionResult

C1 = "services/auth-service.md"
C2 = "databases/postgresql.md"


def _chunk(chunk_id: str, content: str) -> Chunk:
    return Chunk(chunk_id=chunk_id, document=chunk_id.split("#")[0], content=content)


def _result(chunk_id: str, *entities: tuple[str, str]) -> ExtractionResult:
    return ExtractionResult.model_validate(
        {
            "entities": [
                {
                    "id": "x:y",
                    "type": etype,
                    "canonical_name": name,
                    "confidence": 0.95,
                    "source_chunk_id": chunk_id,
                }
                for name, etype in entities
            ],
            "relationships": [],
        }
    )


# --------------------------------------------------------------------------- #
# chunk -> entity ids (pure)
# --------------------------------------------------------------------------- #
def test_entity_ids_by_chunk_resolves_and_groups() -> None:
    results = [
        _result(C1, ("Auth Service", "Service"), ("the Auth Service", "Service")),
        _result(C2, ("PostgreSQL", "Database")),
    ]
    mapping = entity_ids_by_chunk(results)

    assert mapping[C1] == ["service:auth-service"]  # both names -> one resolved id
    assert mapping[C2] == ["database:postgresql"]


def test_entity_ids_by_chunk_uses_source_chunk_id_not_result_order() -> None:
    # one ExtractionResult can carry entities stamped for different chunks
    mixed = ExtractionResult.model_validate(
        {
            "entities": [
                {"id": "x", "type": "Database", "canonical_name": "Redis",
                 "confidence": 0.9, "source_chunk_id": C2},
                {"id": "y", "type": "Service", "canonical_name": "Auth Service",
                 "confidence": 0.9, "source_chunk_id": C1},
            ],
            "relationships": [],
        }
    )
    mapping = entity_ids_by_chunk([mixed])
    assert mapping == {C2: ["database:redis"], C1: ["service:auth-service"]}


# --------------------------------------------------------------------------- #
# document shaping (pure)
# --------------------------------------------------------------------------- #
def test_documents_carry_chunk_metadata() -> None:
    chunks = [_chunk(C1, "The Auth Service uses PostgreSQL."), _chunk(C2, "PostgreSQL 16.")]
    docs = _documents(chunks, {C1: ["service:auth-service", "database:postgresql"]})

    assert docs[0].page_content == "The Auth Service uses PostgreSQL."
    assert docs[0].metadata == {
        "chunk_id": C1,
        "document": C1,
        "entity_ids": ["service:auth-service", "database:postgresql"],
    }
    # a chunk with no extracted entities still gets a document, with an empty list
    assert docs[1].metadata["entity_ids"] == []


# --------------------------------------------------------------------------- #
# GATE — real pgvector
# --------------------------------------------------------------------------- #
@pytest.mark.pgvector
def test_load_vector_is_idempotent_and_searchable() -> None:
    chunks = [
        _chunk(C1, "The Auth Service issues JWT access tokens after login."),
        _chunk(C2, "PostgreSQL is the primary relational database, deployed on RDS."),
        _chunk("protocols/grpc.md", "gRPC is used for internal service-to-service calls."),
    ]
    results = [
        _result(C1, ("Auth Service", "Service")),
        _result(C2, ("PostgreSQL", "Database")),
        _result("protocols/grpc.md", ("gRPC", "Protocol")),
    ]

    store = vector_store()
    load_vector(chunks, results, store=store, wipe_first=True)
    first = store.similarity_search("meridian", k=50)
    load_vector(chunks, results, store=store)  # re-run: upsert, no duplicates
    second = store.similarity_search("meridian", k=50)

    assert len(first) == len(second) == len(chunks)

    hits = store.similarity_search_with_score("Which database does Meridian use?", k=1)
    doc, score = hits[0]
    assert doc.metadata["chunk_id"] == C2
    assert doc.metadata["entity_ids"] == ["database:postgresql"]
    assert isinstance(score, float)

    assert len(store.embeddings.embed_query("dimension check")) == 384

    store.delete_collection()


@pytest.mark.pgvector
def test_collection_name_is_stable() -> None:
    assert vector_store().collection_name == COLLECTION_NAME
