"""Phase 4.1: synthesis.

Unit tests use a stub model (no API). The ``llm`` gate runs the real pipeline +
model over `tests/fixtures/synthesis_eval.json` and checks each answer is
coherent and fully cited.
"""

from __future__ import annotations

import json

import pytest

from src.config import REPO_ROOT
from src.models.answer import Citation, GraphFact, MergedContext, Passage
from src.pipeline.graph import run_pipeline
from src.pipeline.synthesize import SynthesisResult, synthesize

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "synthesis_eval.json"
_NO_ANSWER = "The retrieved context does not contain"


def _load_eval_set() -> list[dict]:
    return json.loads(FIXTURE.read_text("utf-8"))["questions"]


def _routing_used(route: str) -> str:
    return route if route in ("VECTOR", "GRAPH", "HYBRID") else "HYBRID"


def _check(item: dict) -> tuple[bool, str]:
    """Full pipeline + synthesize; verify coherent + every citation grounded."""
    state = run_pipeline(item["question"])
    context = state["context"]
    answer = synthesize(
        item["question"], context, routing_used=_routing_used(state["route_used"])
    )
    retrieved = set(context.chunk_ids)
    problems: list[str] = []
    if not answer.answer.strip() or answer.answer.startswith(_NO_ANSWER):
        problems.append("no answer produced")
    if not answer.citations:
        problems.append("no citations")
    for c in answer.citations:
        if not c.chunk_id or c.chunk_id not in retrieved:
            problems.append(f"citation {c.chunk_id!r} not in retrieved set")
    missing = [m for m in item.get("must_mention", []) if m.lower() not in answer.answer.lower()]
    if missing:
        problems.append(f"answer missing {missing}")
    return not problems, "; ".join(problems)


class StubModel:
    def __init__(self, result: SynthesisResult) -> None:
        self.result = result
        self.calls = 0

    def invoke(self, _messages: object) -> SynthesisResult:
        self.calls += 1
        return self.result


def _context() -> MergedContext:
    return MergedContext(
        graph_facts=[GraphFact(text="Auth Service uses PostgreSQL.", source_chunk_id="g.md")],
        passages=[Passage(chunk_id="v.md", document="v.md", content="body", score=0.1)],
        chunk_ids=["g.md", "v.md"],
    )


# --------------------------------------------------------------------------- #
# unit
# --------------------------------------------------------------------------- #
def test_assembles_grounded_answer_from_model_result() -> None:
    stub = StubModel(
        SynthesisResult(
            answer="The Auth Service uses PostgreSQL [g.md].",
            citations=[Citation(claim="Auth Service uses PostgreSQL", chunk_id="g.md", source_type="GRAPH")],
        )
    )
    answer = synthesize("q", _context(), routing_used="GRAPH", model=stub)
    assert answer.routing_used == "GRAPH"
    assert answer.citations[0].chunk_id == "g.md"
    assert answer.graph_paths == ["Auth Service uses PostgreSQL."]
    assert answer.vector_passages == ["v.md"]
    assert answer.latency_ms >= 0.0


def test_empty_context_short_circuits_without_calling_the_model() -> None:
    stub = StubModel(SynthesisResult(answer="unused"))
    answer = synthesize("q", MergedContext(), routing_used="VECTOR", model=stub)
    assert stub.calls == 0
    assert answer.citations == []
    assert answer.answer.startswith(_NO_ANSWER)


def test_passes_through_multiple_citations() -> None:
    stub = StubModel(
        SynthesisResult(
            answer="a [g.md] b [v.md]",
            citations=[
                Citation(claim="a", chunk_id="g.md", source_type="GRAPH"),
                Citation(claim="b", chunk_id="v.md", source_type="VECTOR"),
            ],
        )
    )
    answer = synthesize("q", _context(), routing_used="HYBRID", model=stub)
    assert [c.chunk_id for c in answer.citations] == ["g.md", "v.md"]


# --------------------------------------------------------------------------- #
# GATE — real pipeline + model
# --------------------------------------------------------------------------- #
@pytest.mark.llm
@pytest.mark.neo4j
@pytest.mark.pgvector
def test_synthesis_gate() -> None:
    failed = [
        (item["question"], detail)
        for item in _load_eval_set()
        for ok, detail in [_check(item)]
        if not ok
    ]
    assert not failed, f"not coherent / fully cited: {failed}"
