"""Phase 4.1: synthesis.

Unit tests use a stub model (no API). The ``llm`` gate runs the real pipeline +
model over the 5-question sample.
"""

from __future__ import annotations

import pytest

from scripts.eval_synthesis import check, load_eval_set
from src.models.answer import Citation, GraphFact, MergedContext, Passage
from src.pipeline.synthesize import SynthesisResult, synthesize


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
    assert answer.answer.startswith("The retrieved context does not contain")


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
    cases = [check(item) for item in load_eval_set()]
    failed = [(c.question, c.detail) for c in cases if not c.ok]
    assert not failed, f"not coherent / fully cited: {failed}"
