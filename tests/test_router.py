"""Phase 3.1: router — confidence-floor logic (unit) and accuracy (gate).

The labelled set is `tests/fixtures/routing_eval.json` (>= 20 questions, disjoint
from the few-shot block). Gate: accuracy >= the fixture's `accuracy_gate`.
"""

from __future__ import annotations

import json

import pytest

from src.config import REPO_ROOT
from src.models.routing import HYBRID_CONFIDENCE_FLOOR, Route, RoutingDecision
from src.pipeline.router import _SYSTEM_PROMPT, _apply_confidence_floor, route_question

VALID_ROUTES = set(Route.__args__)  # type: ignore[attr-defined]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "routing_eval.json"


def _load_eval_set() -> tuple[list[dict], float]:
    data = json.loads(FIXTURE.read_text("utf-8"))
    return data["questions"], data.get("accuracy_gate", 0.90)


class StubRouter:
    """Returns a canned RoutingDecision, ignoring the prompt."""

    def __init__(self, decision: RoutingDecision) -> None:
        self.decision = decision
        self.calls = 0

    def invoke(self, _messages: object) -> RoutingDecision:
        self.calls += 1
        return self.decision


def _decision(route: str, confidence: float) -> RoutingDecision:
    return RoutingDecision(
        route=route, confidence=confidence, reasoning="stub", entities_detected=[]
    )


# --------------------------------------------------------------------------- #
# confidence floor (pure)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("route", ["VECTOR", "GRAPH", "REFUSE"])
def test_low_confidence_is_downgraded_to_hybrid(route: str) -> None:
    out = _apply_confidence_floor(_decision(route, HYBRID_CONFIDENCE_FLOOR - 0.01))
    assert out.route == "HYBRID"
    assert out.confidence == pytest.approx(HYBRID_CONFIDENCE_FLOOR - 0.01)


def test_confident_route_is_left_alone() -> None:
    assert _apply_confidence_floor(_decision("GRAPH", 0.95)).route == "GRAPH"


def test_hybrid_below_floor_stays_hybrid() -> None:
    assert _apply_confidence_floor(_decision("HYBRID", 0.4)).route == "HYBRID"


def test_route_question_applies_floor_and_passes_through_model() -> None:
    stub = StubRouter(_decision("VECTOR", 0.5))
    decision = route_question("something ambiguous", model=stub)
    assert stub.calls == 1
    assert decision.route == "HYBRID"


def test_route_question_keeps_a_confident_decision() -> None:
    stub = StubRouter(_decision("REFUSE", 0.92))
    assert route_question("should we rewrite everything?", model=stub).route == "REFUSE"


# --------------------------------------------------------------------------- #
# fixture hygiene
# --------------------------------------------------------------------------- #
def test_eval_fixture_is_well_formed_and_disjoint_from_few_shot() -> None:
    questions, gate = _load_eval_set()
    assert len(questions) >= 20
    assert 0.0 < gate <= 1.0
    for item in questions:
        assert item["gold_route"] in VALID_ROUTES
        assert item["question"] not in _SYSTEM_PROMPT  # no few-shot leakage


# --------------------------------------------------------------------------- #
# GATE — live LLM
# --------------------------------------------------------------------------- #
@pytest.mark.llm
def test_router_accuracy_clears_the_gate() -> None:
    questions, gate = _load_eval_set()
    results = [
        (q["gold_route"], route_question(q["question"]).route, q["question"])
        for q in questions
    ]
    misses = [(g, p, q) for g, p, q in results if g != p]
    accuracy = 1 - len(misses) / len(results)
    assert accuracy >= gate, f"accuracy {accuracy:.2f} < {gate}; {misses}"
