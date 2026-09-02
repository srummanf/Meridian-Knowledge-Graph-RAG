"""Phase 3.2: graph retriever.

Unit tests exercise the deterministic half with a stub plan model and a fake
Neo4j client (no services running). The ``neo4j`` test checks the real Cypher +
resolution; the ``llm`` + ``neo4j`` test is the gate.
"""

from __future__ import annotations

import pytest

from scripts.eval_graph_retrieval import check, load_eval_set
from src.config import REPO_ROOT
from src.graph.queries import RESOLVE_ENTITY, RESOLVE_ENTITY_FUZZY
from src.models.answer import GraphFact
from src.pipeline.retrieve_graph import (
    GraphQueryPlan,
    _concern_id,
    _dedupe_facts,
    _neighbor_facts,
    _sentence,
    resolve_mention,
    retrieve_graph,
)


class StubPlan:
    def __init__(self, plan: GraphQueryPlan) -> None:
        self.plan = plan

    def invoke(self, _messages: object) -> GraphQueryPlan:
        return self.plan


class FakeGraph:
    """Returns canned rows per template; RESOLVE_* echoes the name as an id."""

    def __init__(self, rows: dict[str, list[dict]]) -> None:
        self.rows = rows
        self.calls: list[str] = []

    def query(self, template: str, params: dict) -> list[dict]:
        if template in (RESOLVE_ENTITY, RESOLVE_ENTITY_FUZZY):
            name = params["name"]
            return [{"id": f"stub:{name.lower()}", "name": name, "type": "Service"}]
        for key, rows in self.rows.items():
            if key in template:
                self.calls.append(key)
                return rows
        return []


# --------------------------------------------------------------------------- #
# formatting (pure)
# --------------------------------------------------------------------------- #
def test_sentence_uses_the_relationship_verb() -> None:
    assert _sentence("USES", "Auth Service", "PostgreSQL") == "Auth Service uses PostgreSQL."
    assert _sentence("PART_OF", "A", "B") == "A is part of B."


def test_dedupe_facts_keeps_first_citation() -> None:
    facts = [
        GraphFact(text="A uses B.", source_chunk_id="one.md"),
        GraphFact(text="A uses B.", source_chunk_id="two.md"),
        GraphFact(text="C uses D.", source_chunk_id="three.md"),
    ]
    out = _dedupe_facts(facts)
    assert [f.text for f in out] == ["A uses B.", "C uses D."]
    assert out[0].source_chunk_id == "one.md"


def test_neighbor_facts_orient_by_direction() -> None:
    rows = [
        {"rel": "USES", "direction": "to_anchor", "anchor_name": "PostgreSQL",
         "name": "Auth Service", "id": "service:auth-service",
         "source_chunk_id": "s.md", "evidence": "e"},
        {"rel": "DEPENDS_ON", "direction": "from_anchor", "anchor_name": "Billing Service",
         "name": "Django", "id": "library:django", "source_chunk_id": "s.md", "evidence": "e"},
    ]
    facts, nodes = _neighbor_facts(rows)
    assert facts[0].text == "Auth Service uses PostgreSQL."
    assert facts[1].text == "Billing Service depends on Django."
    assert nodes == [("service:auth-service", "Auth Service"), ("library:django", "Django")]


def test_concern_id_maps_the_controlled_vocabulary() -> None:
    assert _concern_id("PII") == "concern:pii"
    assert _concern_id("pci cardholder data") == "concern:pci-cardholder-data"
    assert _concern_id("PostgreSQL") is None


def test_plan_requires_at_least_one_anchor() -> None:
    with pytest.raises(ValueError):
        GraphQueryPlan(intent="neighbors", anchors=[])


# --------------------------------------------------------------------------- #
# wiring (stub model + fake client)
# --------------------------------------------------------------------------- #
def test_retrieve_graph_runs_the_neighbors_template() -> None:
    plan = GraphQueryPlan(
        intent="neighbors", anchors=["PostgreSQL"], relationship="USES",
        direction="to_anchor", neighbor_type="Service",
    )
    fake = FakeGraph({
        "MATCH (anchor {id: $anchor_id})-[r]-(n)": [
            {"rel": "USES", "direction": "to_anchor", "anchor_name": "PostgreSQL",
             "name": "Ledger Service", "id": "service:ledger-service",
             "source_chunk_id": "services/ledger-service.md", "evidence": "x"},
        ]
    })
    result = retrieve_graph("Which services use PostgreSQL?", model=StubPlan(plan), client=fake)
    assert result.template == "neighbors"
    assert result.node_names == ["Ledger Service"]
    assert result.facts[0].text == "Ledger Service uses PostgreSQL."
    assert result.facts[0].source_chunk_id == "services/ledger-service.md"


def test_retrieve_graph_returns_empty_when_anchor_unresolved() -> None:
    class NoMatch(FakeGraph):
        def query(self, template: str, params: dict) -> list[dict]:
            return []

    plan = GraphQueryPlan(intent="lookup", anchors=["Nonexistent Thing"])
    result = retrieve_graph("what is it", model=StubPlan(plan), client=NoMatch({}))
    assert result.facts == []
    assert result.node_names == []
    assert result.resolved_anchors == {"Nonexistent Thing": ""}


# --------------------------------------------------------------------------- #
# real graph (deterministic path)
# --------------------------------------------------------------------------- #
@pytest.mark.neo4j
def test_resolve_mention_hits_names_aliases_and_concerns() -> None:
    from src.graph.client import graph_client

    client = graph_client()
    assert resolve_mention("PostgreSQL", client) == "database:postgresql"
    assert resolve_mention("PCI cardholder data", client) == "concern:pci-cardholder-data"
    assert resolve_mention("not a real entity xyz", client) is None


@pytest.mark.neo4j
def test_neighbors_query_is_fast_and_correct() -> None:
    from src.graph.client import graph_client

    plan = GraphQueryPlan(
        intent="neighbors", anchors=["PostgreSQL"], relationship="USES",
        direction="to_anchor", neighbor_type="Service",
    )
    result = retrieve_graph("q", model=StubPlan(plan), client=graph_client())
    assert set(result.node_names) == {
        "Auth Service", "User Service", "Billing Service",
        "Ledger Service", "Reporting Service",
    }
    assert result.query_ms < 200


# --------------------------------------------------------------------------- #
# GATE — real plan LLM + real graph
# --------------------------------------------------------------------------- #
@pytest.mark.llm
@pytest.mark.neo4j
def test_graph_retrieval_gate() -> None:
    from src.graph.client import graph_client

    questions, budget = load_eval_set()
    client = graph_client()
    cases = [check(item, client=client) for item in questions]
    failed = [(c.question, c.detail) for c in cases if not c.ok]
    slow = [(c.question, c.ms) for c in cases if c.ms > budget]
    assert not failed, f"wrong node sets: {failed}"
    assert not slow, f"over {budget}ms: {slow}"


def test_gate_fixture_matches_the_benchmark_refs() -> None:
    questions, _ = load_eval_set()
    assert {q["benchmark_ref"] for q in questions} == {"B09", "B14", "B16", "B17", "B24"}
    benchmark = (REPO_ROOT / "data" / "benchmark" / "questions.md").read_text("utf-8")
    for item in questions:
        assert f"**{item['benchmark_ref']}." in benchmark
