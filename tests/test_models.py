"""Phase 1.1 gate: models accept good data and reject bad data.

Bad = unknown enum value or out-of-range confidence (CLAUDE.md phases §1.1).
Also covers the deterministic-ID helpers, since the whole graph keys on them.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models import (
    Citation,
    Entity,
    ExtractionResult,
    GroundedAnswer,
    Passage,
    Relationship,
    RoutingDecision,
    make_entity_id,
    slugify,
)

# --------------------------------------------------------------------------- #
# Fixtures: minimal valid payloads
# --------------------------------------------------------------------------- #
GOOD_ENTITY = {
    "id": "service:auth-service",
    "type": "Service",
    "canonical_name": "Auth Service",
    "aliases": ["authn-svc"],
    "properties": {"version": "5.4"},
    "confidence": 0.98,
}

GOOD_RELATIONSHIP = {
    "source_id": "service:auth-service",
    "source_name": "Auth Service",
    "type": "USES",
    "target_id": "database:postgresql",
    "target_name": "PostgreSQL",
    "properties": {"purpose": "credential store"},
    "confidence": 0.97,
    "evidence": "The Auth Service uses PostgreSQL as its credential store.",
}


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_entity_accepts_good_data() -> None:
    entity = Entity.model_validate(GOOD_ENTITY)
    assert entity.type == "Service"
    assert entity.source_chunk_id == ""  # pipeline stamps it later


def test_relationship_accepts_good_data() -> None:
    rel = Relationship.model_validate(GOOD_RELATIONSHIP)
    assert rel.type == "USES"
    assert rel.evidence.startswith("The Auth Service")


def test_extraction_result_roundtrips() -> None:
    result = ExtractionResult.model_validate(
        {"entities": [GOOD_ENTITY], "relationships": [GOOD_RELATIONSHIP]}
    )
    assert len(result.entities) == 1
    assert len(result.relationships) == 1


def test_extraction_result_defaults_to_empty() -> None:
    result = ExtractionResult()
    assert result.entities == []
    assert result.relationships == []


def test_entity_optional_fields_default() -> None:
    entity = Entity.model_validate(
        {
            "id": "language:python",
            "type": "Language",
            "canonical_name": "Python",
            "confidence": 0.99,
        }
    )
    assert entity.aliases == []
    assert entity.properties == {}


def test_routing_decision_accepts_each_route() -> None:
    for route in ("VECTOR", "GRAPH", "HYBRID", "REFUSE"):
        decision = RoutingDecision.model_validate(
            {"route": route, "confidence": 0.9, "reasoning": "because"}
        )
        assert decision.route == route
        assert decision.entities_detected == []


def test_grounded_answer_accepts_good_data() -> None:
    answer = GroundedAnswer.model_validate(
        {
            "question": "Which services use PostgreSQL?",
            "answer": "The Auth Service does [services/auth-service.md].",
            "citations": [
                {
                    "claim": "The Auth Service uses PostgreSQL",
                    "chunk_id": "services/auth-service.md",
                    "source_type": "GRAPH",
                }
            ],
            "routing_used": "GRAPH",
            "latency_ms": 1180.0,
        }
    )
    assert answer.citations[0].source_type == "GRAPH"
    assert answer.graph_paths == []


# --------------------------------------------------------------------------- #
# Rejection: unknown enum values
# --------------------------------------------------------------------------- #
def test_entity_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        Entity.model_validate({**GOOD_ENTITY, "type": "Microservice"})


def test_relationship_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        Relationship.model_validate({**GOOD_RELATIONSHIP, "type": "REQUIRES"})


def test_routing_decision_rejects_unknown_route() -> None:
    with pytest.raises(ValidationError):
        RoutingDecision.model_validate(
            {"route": "SQL", "confidence": 0.9, "reasoning": "x"}
        )


def test_citation_rejects_unknown_source_type() -> None:
    with pytest.raises(ValidationError):
        Citation.model_validate(
            {"claim": "x", "chunk_id": "y", "source_type": "KEYWORD"}
        )


def test_grounded_answer_rejects_refuse_as_routing_used() -> None:
    # REFUSE is a router route, never a routing_used on an answer.
    with pytest.raises(ValidationError):
        GroundedAnswer.model_validate(
            {
                "question": "q",
                "answer": "a",
                "routing_used": "REFUSE",
                "latency_ms": 1.0,
            }
        )


# --------------------------------------------------------------------------- #
# Rejection: out-of-range confidence
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0, -1.0])
def test_entity_rejects_out_of_range_confidence(bad: float) -> None:
    with pytest.raises(ValidationError):
        Entity.model_validate({**GOOD_ENTITY, "confidence": bad})


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_relationship_rejects_out_of_range_confidence(bad: float) -> None:
    with pytest.raises(ValidationError):
        Relationship.model_validate({**GOOD_RELATIONSHIP, "confidence": bad})


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_routing_decision_rejects_out_of_range_confidence(bad: float) -> None:
    with pytest.raises(ValidationError):
        RoutingDecision.model_validate(
            {"route": "GRAPH", "confidence": bad, "reasoning": "x"}
        )


def test_confidence_floor_value_is_a_boundary_not_a_validator() -> None:
    # 0.80 is the ingest drop threshold; the model still accepts lower values so
    # the pipeline can log what it dropped.
    entity = Entity.model_validate({**GOOD_ENTITY, "confidence": 0.5})
    assert entity.confidence == 0.5


# --------------------------------------------------------------------------- #
# Rejection: missing / empty required fields
# --------------------------------------------------------------------------- #
def test_relationship_rejects_empty_evidence() -> None:
    with pytest.raises(ValidationError):
        Relationship.model_validate({**GOOD_RELATIONSHIP, "evidence": ""})


def test_entity_rejects_missing_canonical_name() -> None:
    payload = {k: v for k, v in GOOD_ENTITY.items() if k != "canonical_name"}
    with pytest.raises(ValidationError):
        Entity.model_validate(payload)


def test_passage_rejects_empty_content() -> None:
    with pytest.raises(ValidationError):
        Passage.model_validate(
            {"chunk_id": "a", "document": "a.md", "content": "", "score": 0.1}
        )


# --------------------------------------------------------------------------- #
# Deterministic IDs (ONTOLOGY.md §4)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Auth Service", "auth-service"),
        ("PostgreSQL", "postgresql"),
        ("OAuth2", "oauth2"),
        ("AWS RDS", "aws-rds"),
        ("mTLS", "mtls"),
        ("CVE-2021-44228", "cve-2021-44228"),
        ("  Spaced  Out  ", "spaced-out"),
    ],
)
def test_slugify(name: str, expected: str) -> None:
    assert slugify(name) == expected


@pytest.mark.parametrize(
    ("entity_type", "name", "expected"),
    [
        ("Service", "Auth Service", "service:auth-service"),
        ("Database", "PostgreSQL", "database:postgresql"),
        ("SecurityMechanism", "OAuth2", "securitymechanism:oauth2"),
        ("Vulnerability", "CVE-2021-44228", "vulnerability:cve-2021-44228"),
    ],
)
def test_make_entity_id(entity_type: str, name: str, expected: str) -> None:
    assert make_entity_id(entity_type, name) == expected
