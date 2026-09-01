"""Phase 1.4 gate (resolution half): every ONTOLOGY §3 alias collapses to one node.

Also covers article stripping, version peeling, type override, and the
entity/relationship merge keys. No database — resolution is pure.
"""

from __future__ import annotations

import pytest

from src.config import DATA_DIR
from src.ingest.resolve import (
    _endpoint_index,
    _merge_entities,
    _merge_relationships,
    resolve,
    resolve_entity,
    resolve_relationship,
)
from src.models.domain import Entity, Relationship, make_entity_id
from src.models.extraction import ExtractionResult


def _entity(name: str, etype: str = "Service", conf: float = 0.9, **props: str) -> Entity:
    return Entity(
        id="tmp:tmp",
        type=etype,
        canonical_name=name,
        properties=props,
        confidence=conf,
        source_chunk_id="c1",
    )


def _rel(src: str, rtype: str, tgt: str, *, chunk: str = "c1", conf: float = 0.9) -> Relationship:
    return Relationship(
        source_id="tmp:src",
        source_name=src,
        type=rtype,
        target_id="tmp:tgt",
        target_name=tgt,
        confidence=conf,
        evidence=f"{src} {rtype} {tgt}",
        source_chunk_id=chunk,
    )


# --------------------------------------------------------------------------- #
# alias table parsing + the gate
# --------------------------------------------------------------------------- #
def _ontology_alias_rows() -> list[tuple[str, str, str]]:
    """(name_or_alias, canonical, type) for every cell in the §3 table."""
    text = (DATA_DIR / "ONTOLOGY.md").read_text(encoding="utf-8")
    section = text[text.index("## 3.") : text.index("## 4.", text.index("## 3."))]
    rows: list[tuple[str, str, str]] = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 3 or cells[0] in ("Canonical name", "") or set(cells[0]) <= {"-"}:
            continue
        canonical, etype, aliases = cells
        rows.append((canonical, canonical, etype))
        if aliases and aliases != "—":
            rows.extend((a.strip(), canonical, etype) for a in aliases.split(","))
    return rows


ALIAS_ROWS = _ontology_alias_rows()


def test_alias_index_has_all_28_canonical_entities() -> None:
    canonicals = {(c, t) for _, c, t in ALIAS_ROWS}
    assert len(canonicals) == 28


@pytest.mark.parametrize("mention,canonical,etype", ALIAS_ROWS)
def test_every_alias_resolves_to_its_canonical_node(
    mention: str, canonical: str, etype: str
) -> None:
    # LLM deliberately given the wrong type to prove the table overrides it.
    resolved = resolve_entity(_entity(mention, etype="Product"))
    assert resolved.canonical_name == canonical
    assert resolved.type == etype
    assert resolved.id == make_entity_id(etype, canonical)


# --------------------------------------------------------------------------- #
# normalisation details
# --------------------------------------------------------------------------- #
def test_leading_article_is_stripped() -> None:
    assert resolve_entity(_entity("the gateway")).id == "service:api-gateway"


def test_trailing_version_moves_to_properties() -> None:
    resolved = resolve_entity(_entity("PostgreSQL 14.2", etype="Database"))
    assert resolved.id == "database:postgresql"
    assert resolved.properties["version"] == "14.2"


def test_versionlike_alias_is_not_split() -> None:
    # "OAuth 2.0" is an alias, not "OAuth" + version 2.0
    resolved = resolve_entity(_entity("OAuth 2.0", etype="SecurityMechanism"))
    assert resolved.id == "securitymechanism:oauth2"
    assert "version" not in resolved.properties


def test_unknown_entity_keeps_llm_name_and_type() -> None:
    resolved = resolve_entity(_entity("Reporting API", etype="API"))
    assert resolved.id == "api:reporting-api"
    assert resolved.type == "API"


def test_original_name_kept_as_alias_when_renamed() -> None:
    resolved = resolve_entity(_entity("Postgres", etype="Database"))
    assert "Postgres" in resolved.aliases


# --------------------------------------------------------------------------- #
# merging
# --------------------------------------------------------------------------- #
def test_merge_entities_unions_aliases_and_takes_max_confidence() -> None:
    a = resolve_entity(_entity("PostgreSQL", etype="Database", conf=0.8))
    b = resolve_entity(_entity("Postgres", etype="Database", conf=0.95))
    [merged] = _merge_entities([a, b])
    assert merged.confidence == 0.95
    assert "Postgres" in merged.aliases


def test_merge_entities_keeps_version_from_whichever_occurrence_has_it() -> None:
    a = resolve_entity(_entity("PostgreSQL", etype="Database"))
    b = resolve_entity(_entity("PostgreSQL 16.1", etype="Database"))
    [merged] = _merge_entities([a, b])
    assert merged.properties.get("version") == "16.1"


INDEX = _endpoint_index([])  # alias-table-backed, like resolve() builds


def test_merge_relationships_dedupes_on_chunk_key() -> None:
    rels = [
        _rel("Auth Service", "USES", "PostgreSQL", chunk="c1", conf=0.8),
        _rel("Auth Service", "USES", "PostgreSQL", chunk="c1", conf=0.9),
    ]
    resolved = _merge_relationships(
        [resolve_relationship(r, INDEX) for r in rels]
    )
    assert len(resolved) == 1
    assert resolved[0].confidence == 0.9


def test_merge_relationships_keeps_parallel_edges_from_different_chunks() -> None:
    resolved = _merge_relationships(
        [
            resolve_relationship(_rel("Auth Service", "USES", "PostgreSQL", chunk="c1"), INDEX),
            resolve_relationship(_rel("Auth Service", "USES", "PostgreSQL", chunk="c2"), INDEX),
        ]
    )
    assert len(resolved) == 2


# --------------------------------------------------------------------------- #
# relationship endpoint resolution
# --------------------------------------------------------------------------- #
def test_relationship_endpoints_resolve_via_alias() -> None:
    rel = resolve_relationship(_rel("the gateway", "USES", "Redis cache"), INDEX)
    assert rel.source_id == "service:api-gateway"
    assert rel.target_id == "database:redis"


def test_handles_target_maps_to_controlled_concern() -> None:
    rel = resolve_relationship(_rel("Auth Service", "HANDLES", "pii"), INDEX)
    assert rel.target_id == "concern:pii"
    assert rel.target_name == "PII"


def test_self_loop_is_dropped() -> None:
    assert resolve_relationship(_rel("Redis", "ALTERNATIVE_TO", "Redis cache"), INDEX) is None


def test_alternative_to_is_stored_one_direction() -> None:
    index = INDEX
    forward = resolve_relationship(_rel("Redis", "ALTERNATIVE_TO", "Elasticsearch"), index)
    backward = resolve_relationship(_rel("Elasticsearch", "ALTERNATIVE_TO", "Redis"), index)
    assert (forward.source_id, forward.target_id) == (backward.source_id, backward.target_id)


# --------------------------------------------------------------------------- #
# end to end
# --------------------------------------------------------------------------- #
def _extraction() -> ExtractionResult:
    return ExtractionResult.model_validate(
        {
            "entities": [
                {"id": "service:auth-service", "type": "Service", "canonical_name": "the auth svc", "confidence": 0.95, "source_chunk_id": "services/auth-service.md"},
                {"id": "database:postgresql", "type": "Database", "canonical_name": "Postgres", "confidence": 0.9, "source_chunk_id": "services/auth-service.md"},
                {"id": "database:postgresql", "type": "Product", "canonical_name": "PostgreSQL 15.2", "confidence": 0.97, "source_chunk_id": "databases/postgresql.md"},
            ],
            "relationships": [
                {"source_id": "service:auth-service", "source_name": "the auth svc", "type": "USES", "target_id": "database:postgresql", "target_name": "Postgres", "confidence": 0.96, "evidence": "the auth svc USES Postgres", "source_chunk_id": "services/auth-service.md"},
            ],
        }
    )


def test_resolve_end_to_end_collapses_and_types() -> None:
    entities, relationships = resolve([_extraction()])
    assert len(entities) == 2
    pg = next(e for e in entities if e.id == "database:postgresql")
    assert pg.type == "Database"  # not the "Product" mislabel
    assert pg.properties.get("version") == "15.2"
    assert len(relationships) == 1
    assert relationships[0].source_id == "service:auth-service"
    assert relationships[0].target_id == "database:postgresql"


def test_resolve_is_deterministic() -> None:
    first = resolve([_extraction()])
    second = resolve([_extraction()])
    assert [e.model_dump() for e in first[0]] == [e.model_dump() for e in second[0]]
    assert [r.model_dump() for r in first[1]] == [r.model_dump() for r in second[1]]


def test_no_orphan_relationship_endpoints_in_a_clean_resolve() -> None:
    entities, relationships = resolve([_extraction()])
    ids = {e.id for e in entities}
    for rel in relationships:
        assert rel.source_id in ids
        assert rel.target_id in ids or rel.target_id.startswith("concern:")
