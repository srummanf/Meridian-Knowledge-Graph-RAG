"""Every Cypher string in the project lives here (rules.md §3.1).

Callers pass parameters to :meth:`Neo4jGraph.query`; nothing interpolates values
into a query, and the LLM never authors Cypher (no ``GraphCypherQAChain``).

Cypher cannot parameterise a label or a relationship type, so there is one
write template per entity type (11) and one per relationship type (12). The
template *catalogues* are built once from the closed enums in
:mod:`src.models.domain` — the only place a type name is formatted into a string.
"""

from __future__ import annotations

from typing import get_args

from src.models.domain import EntityType, RelationType

# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
SCHEMA_STATEMENTS: tuple[str, ...] = (
    "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
    "CREATE CONSTRAINT concern_id IF NOT EXISTS FOR (c:Concern) REQUIRE c.id IS UNIQUE",
    "CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.canonical_name)",
    "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.type)",
)

WIPE = "MATCH (n) DETACH DELETE n"

# --------------------------------------------------------------------------- #
# Entity upsert — one per type (deterministic id => MERGE is idempotent)
# --------------------------------------------------------------------------- #
_UPSERT_ENTITY = """\
MERGE (e:Entity {{id: $id}})
SET e += $props
SET e:`{label}`
"""

ENTITY_TEMPLATES: dict[str, str] = {
    label: _UPSERT_ENTITY.format(label=label) for label in get_args(EntityType)
}

# --------------------------------------------------------------------------- #
# Relationship upsert — one per type, keyed on source_chunk_id
# --------------------------------------------------------------------------- #
_UPSERT_REL = """\
MATCH (s:Entity {{id: $source_id}})
MATCH (t:Entity {{id: $target_id}})
MERGE (s)-[r:`{rel}` {{source_chunk_id: $source_chunk_id}}]->(t)
SET r.evidence = $evidence, r.confidence = $confidence, r += $props
"""

# HANDLES points at a controlled-vocabulary Concern node, not an Entity.
_UPSERT_HANDLES = """\
MATCH (s:Entity {id: $source_id})
MERGE (c:Concern {id: $target_id})
SET c.name = $target_name
MERGE (s)-[r:HANDLES {source_chunk_id: $source_chunk_id}]->(c)
SET r.evidence = $evidence, r.confidence = $confidence
"""

RELATIONSHIP_TEMPLATES: dict[str, str] = {
    rel: (_UPSERT_HANDLES if rel == "HANDLES" else _UPSERT_REL.format(rel=rel))
    for rel in get_args(RelationType)
}

# --------------------------------------------------------------------------- #
# Counts (gate verification)
# --------------------------------------------------------------------------- #
COUNT_ENTITIES = "MATCH (e:Entity) RETURN count(e) AS n"
COUNT_RELATIONSHIPS = "MATCH ()-[r]->() RETURN count(r) AS n"
COUNT_RELATIONSHIPS_MISSING_EVIDENCE = (
    "MATCH ()-[r]->() WHERE r.evidence IS NULL OR r.source_chunk_id IS NULL "
    "RETURN count(r) AS n"
)
COUNT_ORPHAN_ENTITIES = "MATCH (e:Entity) WHERE NOT (e)--() RETURN count(e) AS n"
ENTITY_TYPE_BREAKDOWN = (
    "MATCH (e:Entity) RETURN e.type AS type, count(*) AS n ORDER BY n DESC"
)
RELATIONSHIP_TYPE_BREAKDOWN = (
    "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY n DESC"
)

# Read templates for retrieval (entity_by_name, neighbors_1hop, ...) arrive in
# Phase 3.2.
