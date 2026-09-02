"""Phase 4.3: API.

Fast tests stub ``answer_question`` and override the datastore dependency — no
Neo4j, Postgres, or LLM. The ``llm+neo4j+pgvector`` gate drives the real
pipeline once per route and records latency.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import require_datastores
from src.api.main import app
from src.models.answer import Citation, GroundedAnswer
from src.pipeline import graph as graph_module


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app.dependency_overrides[require_datastores] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


def _stub_state(**over):
    state = {
        "question": "q",
        "route_used": "GRAPH",
        "decision": None,
        "context": None,
        "answer": GroundedAnswer(
            question="q",
            answer="Five services use PostgreSQL.",
            citations=[Citation(claim="c", chunk_id="databases/postgresql.md", source_type="GRAPH")],
            routing_used="GRAPH",
            latency_ms=1.0,
        ),
    }
    state.update(over)
    return state


# --------------------------------------------------------------------------- #
# /query
# --------------------------------------------------------------------------- #
def test_query_returns_grounded_answer(client, monkeypatch) -> None:
    monkeypatch.setattr(graph_module, "answer_question", lambda _q: _stub_state())
    monkeypatch.setattr("src.api.main.answer_question", lambda _q: _stub_state())
    body = client.post("/query", json={"question": "Which services use PostgreSQL?"})
    assert body.status_code == 200
    data = body.json()
    assert data["routing_used"] == "GRAPH"
    assert data["citations"][0]["chunk_id"] == "databases/postgresql.md"
    assert data["latency_ms"] > 0


def test_refuse_route_is_422_out_of_scope(client, monkeypatch) -> None:
    from src.models.routing import RoutingDecision

    refused = _stub_state(
        route_used="REFUSE",
        answer=None,
        decision=RoutingDecision(route="REFUSE", confidence=0.9, reasoning="opinion", entities_detected=[]),
    )
    monkeypatch.setattr("src.api.main.answer_question", lambda _q: refused)
    body = client.post("/query", json={"question": "Is PostgreSQL better than MySQL?"})
    assert body.status_code == 422
    assert body.json()["error"] == "out_of_scope"
    assert body.json()["reason"] == "opinion"


def test_blank_question_is_400(client) -> None:
    body = client.post("/query", json={"question": "   "})
    assert body.status_code == 400
    assert body.json()["error"] == "bad_request"


def test_missing_question_is_400(client) -> None:
    body = client.post("/query", json={})
    assert body.status_code == 400


def test_oversized_question_is_400(client) -> None:
    body = client.post("/query", json={"question": "x" * 1001})
    assert body.status_code == 400


def test_query_is_503_when_a_datastore_is_down(monkeypatch) -> None:
    # no dependency override here -> the real require_datastores runs
    monkeypatch.setattr(
        "src.api.dependencies.datastore_status",
        lambda: {"neo4j": "ok", "postgres": "down: connection refused"},
    )
    body = TestClient(app).post("/query", json={"question": "anything"})
    assert body.status_code == 503
    assert body.json()["error"] == "unavailable"


# --------------------------------------------------------------------------- #
# /health
# --------------------------------------------------------------------------- #
def test_health_ok(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.api.main.datastore_status",
        lambda: {"neo4j": "ok", "postgres": "ok"},
    )
    body = TestClient(app).get("/health")
    assert body.status_code == 200
    assert body.json() == {"status": "ok", "neo4j": "ok", "postgres": "ok"}


def test_health_degraded_still_200(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.api.main.datastore_status",
        lambda: {"neo4j": "ok", "postgres": "down: boom"},
    )
    body = TestClient(app).get("/health")
    assert body.status_code == 200
    assert body.json()["status"] == "degraded"


# --------------------------------------------------------------------------- #
# GATE — real pipeline, one question per route
# --------------------------------------------------------------------------- #
_GATE_CASES = [
    ("What is the Auth Service?", "VECTOR", 200),
    ("Which services use PostgreSQL?", "GRAPH", 200),
    ("What is the Ledger API and which services consume it?", "HYBRID", 200),
    ("Should the Payments Team rewrite the Ledger Service in Go?", "REFUSE", 422),
]


def _gate_check(real_client: TestClient, question: str, route: str, status: int) -> str | None:
    r = real_client.post("/query", json={"question": question})
    body = r.json()
    if r.status_code != status:
        return f"{question}: status {r.status_code} != {status}"
    if r.status_code == 422:
        return None if body.get("error") == "out_of_scope" else f"{question}: {body!r}"
    if not body.get("citations"):
        return f"{question}: no citations"
    vector_ids = set(body.get("vector_passages", []))
    for c in body["citations"]:
        if c["source_type"] == "VECTOR" and c["chunk_id"] not in vector_ids:
            return f"{question}: VECTOR citation {c['chunk_id']} not retrieved"
    if route != "HYBRID" and body.get("routing_used") != route:
        return f"{question}: routing_used {body.get('routing_used')} != {route}"
    return None


@pytest.mark.llm
@pytest.mark.neo4j
@pytest.mark.pgvector
def test_api_gate() -> None:
    with TestClient(app) as real_client:
        failed = [
            problem
            for q, route, status in _GATE_CASES
            for problem in [_gate_check(real_client, q, route, status)]
            if problem
        ]
    assert not failed, f"route failures: {failed}"
