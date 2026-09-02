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

# --------------------------------------------------------------------------- #
# Read templates (Phase 3.2) — the graph retriever's entire Cypher surface.
#
# These are generic: the relationship type is a ``WHERE type(r) = $rel`` filter,
# never interpolated, so one template serves every edge type. Anchors are
# matched on the unique ``id`` (works for an ``:Entity`` or a ``:Concern``
# HANDLES target). ``$rel`` / ``$neighbor_type`` / ``$direction`` may be null to
# mean "no filter" / "either way". The LLM never sees or writes Cypher — it only
# fills a :class:`~src.pipeline.retrieve_graph.GraphQueryPlan`, which the
# retriever maps to one of these.
# --------------------------------------------------------------------------- #

RESOLVE_ENTITY = """
MATCH (e:Entity)
WHERE toLower(e.canonical_name) = toLower($name)
   OR any(a IN coalesce(e.aliases, []) WHERE toLower(a) = toLower($name))
RETURN e.id AS id, e.canonical_name AS name, e.type AS type
ORDER BY size(e.canonical_name)
LIMIT 1
"""

RESOLVE_ENTITY_FUZZY = """
MATCH (e:Entity)
WHERE toLower(e.canonical_name) CONTAINS toLower($name)
   OR toLower($name) CONTAINS toLower(e.canonical_name)
RETURN e.id AS id, e.canonical_name AS name, e.type AS type
ORDER BY size(e.canonical_name)
LIMIT 1
"""

_DIRECTION_CLAUSE = """
  AND ($direction IS NULL OR $direction = 'either'
       OR ($direction = 'from_anchor' AND startNode(r) = anchor)
       OR ($direction = 'to_anchor'   AND endNode(r)   = anchor))
"""

NEIGHBORS = f"""
MATCH (anchor {{id: $anchor_id}})-[r]-(n)
WHERE ($rel IS NULL OR type(r) = $rel){_DIRECTION_CLAUSE}
  AND ($neighbor_type IS NULL OR n.type = $neighbor_type)
RETURN DISTINCT
  type(r) AS rel,
  CASE WHEN startNode(r) = anchor THEN 'from_anchor' ELSE 'to_anchor' END AS direction,
  anchor.canonical_name AS anchor_name,
  coalesce(n.canonical_name, n.name) AS name,
  n.id AS id, n.type AS type,
  r.source_chunk_id AS source_chunk_id, r.evidence AS evidence
ORDER BY rel, name
"""

COUNT_NEIGHBORS = f"""
MATCH (anchor {{id: $anchor_id}})-[r]-(n)
WHERE ($rel IS NULL OR type(r) = $rel){_DIRECTION_CLAUSE}
  AND ($neighbor_type IS NULL OR n.type = $neighbor_type)
RETURN count(DISTINCT n) AS count
"""

TWO_CONSTRAINT = """
MATCH (n:Entity)-[r1]-(a1 {id: $anchor_id})
WHERE $rel IS NULL OR type(r1) = $rel
MATCH (n)-[r2]-(a2 {id: $second_anchor_id})
WHERE $second_rel IS NULL OR type(r2) = $second_rel
RETURN DISTINCT
  n.id AS id, n.canonical_name AS name, n.type AS type,
  type(r1) AS rel1, coalesce(a1.canonical_name, a1.name) AS anchor1,
  type(r2) AS rel2, coalesce(a2.canonical_name, a2.name) AS anchor2,
  r1.source_chunk_id AS source_chunk_id, r1.evidence AS evidence
ORDER BY name
"""

PATH_BETWEEN = """
MATCH (a {id: $anchor_id}), (b {id: $second_anchor_id})
MATCH p = shortestPath((a)-[*..5]-(b))
UNWIND relationships(p) AS r
RETURN
  type(r) AS rel,
  startNode(r).canonical_name AS source,
  coalesce(endNode(r).canonical_name, endNode(r).name) AS target,
  r.source_chunk_id AS source_chunk_id, r.evidence AS evidence
"""

BLAST_RADIUS = """
MATCH (v {id: $anchor_id})-[a:AFFECTS]->(lib:Entity)
OPTIONAL MATCH (lib)<-[:DEPENDS_ON*1..3]-(svc:Entity)
WITH lib, a, svc WHERE svc IS NULL OR svc.type = 'Service'
OPTIONAL MATCH (svc)-[:PART_OF]->(prod:Entity)
RETURN
  lib.canonical_name AS affected_library,
  a.affected_versions AS affected_versions,
  collect(DISTINCT svc.canonical_name) AS services,
  collect(DISTINCT prod.canonical_name) AS products,
  a.source_chunk_id AS source_chunk_id, a.evidence AS evidence
"""

READ_TEMPLATES: dict[str, str] = {
    "neighbors": NEIGHBORS,
    "count": COUNT_NEIGHBORS,
    "two_constraint": TWO_CONSTRAINT,
    "path": PATH_BETWEEN,
    "blast_radius": BLAST_RADIUS,
    "lookup": NEIGHBORS,  # 1-hop neighbourhood, no filters
}
