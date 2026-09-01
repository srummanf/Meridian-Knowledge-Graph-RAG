"""Phase 1.4 gate (load half): param shaping (unit) + a real MERGE/idempotency run."""

from __future__ import annotations

import json

import pytest

from src.ingest.load_graph import _entity_params, _relationship_params, load_graph
from src.models.domain import Entity, Relationship


def _entity(**kw: object) -> Entity:
    base = dict(
        id="database:postgresql",
        type="Database",
        canonical_name="PostgreSQL",
        aliases=["Postgres"],
        properties={"version": "16.1"},
        confidence=0.98,
        source_chunk_id="databases/postgresql.md",
    )
    base.update(kw)
    return Entity.model_validate(base)


def _rel(**kw: object) -> Relationship:
    base = dict(
        source_id="service:auth-service",
        source_name="Auth Service",
        type="USES",
        target_id="database:postgresql",
        target_name="PostgreSQL",
        properties={"purpose": "credential store"},
        confidence=0.97,
        evidence="The Auth Service uses PostgreSQL as its credential store.",
        source_chunk_id="services/auth-service.md",
    )
    base.update(kw)
    return Relationship.model_validate(base)


# --------------------------------------------------------------------------- #
# param shaping (pure)
# --------------------------------------------------------------------------- #
def test_entity_params_serialises_properties_as_json_and_hoists_version() -> None:
    params = _entity_params(_entity())
    props = params["props"]
    assert params["id"] == "database:postgresql"
    assert props["version"] == "16.1"
    assert json.loads(props["properties_json"]) == {"version": "16.1"}
    assert props["aliases"] == ["Postgres"]


def test_entity_params_handles_empty_properties() -> None:
    props = _entity_params(_entity(properties={}))["props"]
    assert props["properties_json"] == "{}"
    assert "version" not in props


def test_relationship_params_pass_primitive_properties_through() -> None:
    params = _relationship_params(_rel())
    assert params["props"] == {"purpose": "credential store"}
    assert params["source_chunk_id"] == "services/auth-service.md"
    assert params["evidence"].startswith("The Auth Service")


# --------------------------------------------------------------------------- #
# real Neo4j — MERGE, idempotency, citations
# --------------------------------------------------------------------------- #
@pytest.mark.neo4j
def test_load_is_idempotent_and_every_edge_is_cited() -> None:
    from src.graph.client import graph_client, wipe

    client = graph_client()
    wipe(client)

    entities = [
        _entity(),
        _entity(
            id="service:auth-service",
            type="Service",
            canonical_name="Auth Service",
            aliases=[],
            properties={},
        ),
    ]
    relationships = [_rel()]

    first = load_graph(entities, relationships, client=client)
    second = load_graph(entities, relationships, client=client)

    assert first == second, "re-running load_graph changed the counts"
    assert first["entities"] == 2
    assert first["relationships"] == 1
    assert first["relationships_missing_evidence"] == 0
    assert first["skipped"] == 0

    row = client.query(
        "MATCH (:Entity {id:'service:auth-service'})-[r:USES]->(:Entity {id:'database:postgresql'}) "
        "RETURN r.evidence AS evidence, r.source_chunk_id AS chunk, r.purpose AS purpose"
    )[0]
    assert row["chunk"] == "services/auth-service.md"
    assert row["purpose"] == "credential store"

    labels = client.query(
        "MATCH (e:Entity {id:'database:postgresql'}) RETURN labels(e) AS labels"
    )[0]["labels"]
    assert "Database" in labels

    wipe(client)


@pytest.mark.neo4j
def test_handles_relationship_creates_a_concern_node() -> None:
    from src.graph.client import graph_client, wipe

    client = graph_client()
    wipe(client)

    load_graph(
        [_entity(id="service:auth-service", type="Service", canonical_name="Auth Service", aliases=[], properties={})],
        [
            _rel(
                type="HANDLES",
                target_id="concern:pii",
                target_name="PII",
                properties={},
                evidence="The Auth Service handles PII.",
            )
        ],
        client=client,
    )
    concern = client.query("MATCH (c:Concern) RETURN c.id AS id, c.name AS name")
    assert concern == [{"id": "concern:pii", "name": "PII"}]
    wipe(client)
