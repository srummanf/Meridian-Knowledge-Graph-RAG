"""Write resolved entities and relationships into Neo4j via the query templates.

Everything is ``MERGE`` on a deterministic key (rules.md §3.3), so loading the
same graph twice changes no counts. Node ``properties`` (a free-form map) is
stored as a JSON string because Neo4j properties must be primitive; ``version``
is also hoisted to its own property for convenient filtering.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.graph.client import ensure_schema, graph_client, wipe
from src.graph.queries import (
    COUNT_ENTITIES,
    COUNT_RELATIONSHIPS,
    COUNT_RELATIONSHIPS_MISSING_EVIDENCE,
    ENTITY_TEMPLATES,
    RELATIONSHIP_TEMPLATES,
)
from src.logging_config import get_logger
from src.models.domain import Entity, Relationship

if TYPE_CHECKING:
    from langchain_neo4j import Neo4jGraph

log = get_logger("load_graph")


def _entity_params(entity: Entity) -> dict:
    props: dict[str, object] = {
        "id": entity.id,
        "type": entity.type,
        "canonical_name": entity.canonical_name,
        "aliases": entity.aliases,
        "confidence": entity.confidence,
        "source_chunk_id": entity.source_chunk_id,
        "properties_json": json.dumps(entity.properties, sort_keys=True),
    }
    version = entity.properties.get("version")
    if version is not None:
        props["version"] = str(version)
    return {"id": entity.id, "props": props}


def _relationship_params(rel: Relationship) -> dict:
    return {
        "source_id": rel.source_id,
        "target_id": rel.target_id,
        "target_name": rel.target_name,
        "source_chunk_id": rel.source_chunk_id,
        "evidence": rel.evidence,
        "confidence": rel.confidence,
        "props": dict(rel.properties),
    }


def load_graph(
    entities: list[Entity],
    relationships: list[Relationship],
    *,
    client: Neo4jGraph | None = None,
    wipe_first: bool = False,
) -> dict[str, int]:
    """MERGE everything into Neo4j. Returns the post-load counts from the DB."""
    client = client or graph_client()
    ensure_schema(client)
    if wipe_first:
        wipe(client)
        ensure_schema(client)

    for entity in entities:
        client.query(ENTITY_TEMPLATES[entity.type], _entity_params(entity))
    log.info("merged %d entities", len(entities))

    skipped = 0
    for rel in relationships:
        try:
            client.query(RELATIONSHIP_TEMPLATES[rel.type], _relationship_params(rel))
        except Exception as exc:  # noqa: BLE001 - a dangling endpoint must not abort the load
            skipped += 1
            log.error(
                "skipped %s %s->%s: %s",
                rel.type,
                rel.source_id,
                rel.target_id,
                exc,
            )
    log.info("merged %d relationships (%d skipped)", len(relationships) - skipped, skipped)

    counts = {
        "entities": client.query(COUNT_ENTITIES)[0]["n"],
        "relationships": client.query(COUNT_RELATIONSHIPS)[0]["n"],
        "relationships_missing_evidence": client.query(
            COUNT_RELATIONSHIPS_MISSING_EVIDENCE
        )[0]["n"],
        "skipped": skipped,
    }
    log.info("neo4j now holds %(entities)d entities, %(relationships)d relationships", counts)
    return counts
