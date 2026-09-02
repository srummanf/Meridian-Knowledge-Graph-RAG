"""Phase 4.2: citation validation + the full answer pipeline wiring."""

from __future__ import annotations

import json

import pytest

from src.config import REPO_ROOT
from src.models.answer import Citation, GraphFact, GroundedAnswer, MergedContext, Passage
from src.pipeline.graph import answer_question, compile_answer_pipeline
from src.pipeline.synthesize import synthesize
from src.pipeline.validate import validate_answer

_SYNTHESIS_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "synthesis_eval.json"


def _context() -> MergedContext:
    return MergedContext(
        graph_facts=[GraphFact(text="A uses B.", source_chunk_id="g.md")],
        passages=[Passage(chunk_id="v.md", document="v.md", content="body", score=0.1)],
        chunk_ids=["g.md", "v.md"],
    )


def _answer(*chunk_ids: str, notes: list[str] | None = None) -> GroundedAnswer:
    return GroundedAnswer(
        question="q",
        answer="an answer",
        citations=[
            Citation(claim="c", chunk_id=cid, source_type="GRAPH") for cid in chunk_ids
        ],
        routing_used="GRAPH",
        notes=notes or [],
        latency_ms=1.0,
    )


class StubSynth:
    """Stands in for src.pipeline.synthesize.synthesize (used via model=... path)."""

    def __init__(self, result) -> None:
        self.result = result
        self.calls = 0

    def invoke(self, _messages: object):
        self.calls += 1
        return self.result


# --------------------------------------------------------------------------- #
# validate_answer
# --------------------------------------------------------------------------- #
def test_valid_answer_passes_through_untouched() -> None:
    answer = _answer("g.md", "v.md")
    assert validate_answer(answer, _context(), question="q") is answer


def test_regenerates_once_and_keeps_only_valid_citations() -> None:
    from src.pipeline.synthesize import SynthesisResult

    bad = _answer("g.md", "hallucinated.md")
    good = SynthesisResult(
        answer="fixed",
        citations=[Citation(claim="c", chunk_id="g.md", source_type="GRAPH")],
    )
    out = validate_answer(bad, _context(), question="q", model=StubSynth(good))
    assert [c.chunk_id for c in out.citations] == ["g.md"]
    assert out.answer == "fixed"
    assert out.notes == []  # retry produced only valid citations


def test_notes_when_retry_still_cites_outside_the_set() -> None:
    from src.pipeline.synthesize import SynthesisResult

    bad = _answer("nope.md")
    still_bad = SynthesisResult(
        answer="still wrong",
        citations=[Citation(claim="c", chunk_id="still-nope.md", source_type="GRAPH")],
    )
    out = validate_answer(bad, _context(), question="q", model=StubSynth(still_bad))
    assert out.citations == []
    assert len(out.notes) == 1
    assert "still-nope.md" in out.notes[0]


# --------------------------------------------------------------------------- #
# full answer pipeline (fakes for every LLM step)
# --------------------------------------------------------------------------- #
def _pipe(route: str, *, graph_facts=None, passages=None, answer=None):
    from src.models.routing import RoutingDecision
    from src.pipeline.retrieve_graph import GraphRetrieval

    return compile_answer_pipeline(
        router=lambda _q: RoutingDecision(
            route=route, confidence=0.95, reasoning="t", entities_detected=[]
        ),
        graph_fn=lambda _q: GraphRetrieval(facts=graph_facts or []),
        vector_fn=lambda _q: passages or [],
        synthesize_fn=lambda _q, _ctx, ru: answer
        or GroundedAnswer(
            question=_q, answer="synth", citations=[], routing_used=ru, latency_ms=1.0
        ),
        validate_fn=lambda ans, _ctx, _q: ans,
    )


def test_answer_pipeline_runs_synthesize_then_validate() -> None:
    pipe = _pipe(
        "GRAPH",
        graph_facts=[GraphFact(text="A uses B.", source_chunk_id="g.md")],
        answer=_answer("g.md"),
    )
    state = pipe.invoke({"question": "which x", "notes": []})
    assert state["answer"].answer == "an answer"
    assert state["route_used"] == "GRAPH"


def test_answer_pipeline_skips_synthesis_on_refuse() -> None:
    pipe = _pipe("REFUSE")
    state = pipe.invoke({"question": "should we", "notes": []})
    assert state["route_used"] == "REFUSE"
    assert "answer" not in state


def test_pipeline_fallback_note_reaches_the_answer() -> None:
    pipe = _pipe("GRAPH", graph_facts=[], passages=[
        Passage(chunk_id="v.md", document="v.md", content="b", score=0.1)
    ], answer=_answer("v.md"))
    state = pipe.invoke({"question": "which x", "notes": []})
    assert any("fallback" in n for n in state["answer"].notes)


# --------------------------------------------------------------------------- #
# GATE — real pipeline + model
# --------------------------------------------------------------------------- #
@pytest.mark.llm
@pytest.mark.neo4j
@pytest.mark.pgvector
def test_validation_gate() -> None:
    questions = json.loads(_SYNTHESIS_FIXTURE.read_text("utf-8"))["questions"]
    failed: list[tuple[str, str]] = []

    # (1) 100% citation validity through the full pipeline
    for item in questions:
        state = answer_question(item["question"])
        answer = state.get("answer")
        if answer is None:
            failed.append((item["question"], "no answer (refused?)"))
            continue
        retrieved = set(state["context"].chunk_ids)
        bad = [c.chunk_id for c in answer.citations if c.chunk_id not in retrieved]
        if bad:
            failed.append((item["question"], f"invalid: {bad}"))

    # (2) an injected bad citation is caught and removed
    q = "Which services use PostgreSQL?"
    state = answer_question(q)
    context = state["context"]
    base = synthesize(q, context, routing_used="GRAPH")
    poisoned = base.model_copy(update={"citations": [
        *base.citations,
        Citation(claim="fabricated", chunk_id="does/not/exist.md", source_type="GRAPH"),
    ]})
    fixed = validate_answer(poisoned, context, question=q)
    leaked = [c.chunk_id for c in fixed.citations if c.chunk_id not in set(context.chunk_ids)]
    if leaked or not fixed.citations:
        failed.append(("injected bad citation", f"leaked {leaked}"))

    assert not failed, f"invalid citations: {failed}"
