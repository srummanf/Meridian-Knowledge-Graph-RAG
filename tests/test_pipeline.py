"""Phase 3.4: LangGraph wiring. Fakes for all three retrieval callables — the
test is about edges and fallbacks, not retrieval quality (covered in
test_retrieve_graph / test_retrieve_vector).
"""

from __future__ import annotations

from src.models.answer import GraphFact, Passage
from src.models.routing import RoutingDecision
from src.pipeline.graph import compile_pipeline
from src.pipeline.retrieve_graph import GraphRetrieval


def _decision(route: str, conf: float = 0.95) -> RoutingDecision:
    return RoutingDecision(
        route=route, confidence=conf, reasoning="test", entities_detected=[]
    )


def _passage(chunk_id: str) -> Passage:
    return Passage(chunk_id=chunk_id, document=chunk_id, content="body", score=0.1)


def _graph_hit() -> GraphRetrieval:
    return GraphRetrieval(
        facts=[GraphFact(text="A uses B.", source_chunk_id="g.md")],
        node_names=["B"],
    )


def _pipe(route: str, *, graph=None, passages=None):
    return compile_pipeline(
        router=lambda _q: _decision(route),
        graph_fn=lambda _q: graph if graph is not None else GraphRetrieval(),
        vector_fn=lambda _q: passages if passages is not None else [],
    )


def test_vector_route_runs_only_vector() -> None:
    calls: list[str] = []
    pipe = compile_pipeline(
        router=lambda _q: _decision("VECTOR"),
        graph_fn=lambda _q: calls.append("graph") or GraphRetrieval(),
        vector_fn=lambda _q: calls.append("vector") or [_passage("v.md")],
    )
    state = pipe.invoke({"question": "what is x", "notes": []})
    assert calls == ["vector"]
    assert state["route_used"] == "VECTOR"
    assert state["context"].chunk_ids == ["v.md"]


def test_graph_route_with_hits_skips_vector() -> None:
    calls: list[str] = []
    pipe = compile_pipeline(
        router=lambda _q: _decision("GRAPH"),
        graph_fn=lambda _q: calls.append("graph") or _graph_hit(),
        vector_fn=lambda _q: calls.append("vector") or [],
    )
    state = pipe.invoke({"question": "which x use y", "notes": []})
    assert calls == ["graph"]
    assert [f.text for f in state["context"].graph_facts] == ["A uses B."]


def test_graph_empty_falls_back_to_vector() -> None:
    pipe = _pipe("GRAPH", graph=GraphRetrieval(), passages=[_passage("v.md")])
    state = pipe.invoke({"question": "which x use y", "notes": []})
    assert state["context"].chunk_ids == ["v.md"]
    assert any("fallback" in n for n in state["notes"])


def test_hybrid_runs_both_and_merges() -> None:
    calls: list[str] = []
    pipe = compile_pipeline(
        router=lambda _q: _decision("HYBRID"),
        graph_fn=lambda _q: calls.append("graph") or _graph_hit(),
        vector_fn=lambda _q: calls.append("vector") or [_passage("v.md")],
    )
    state = pipe.invoke({"question": "explain and trace x", "notes": []})
    assert calls == ["graph", "vector"]
    assert state["context"].chunk_ids == ["g.md", "v.md"]


def test_refuse_route_retrieves_nothing() -> None:
    calls: list[str] = []
    pipe = compile_pipeline(
        router=lambda _q: _decision("REFUSE"),
        graph_fn=lambda _q: calls.append("graph") or GraphRetrieval(),
        vector_fn=lambda _q: calls.append("vector") or [],
    )
    state = pipe.invoke({"question": "should we rewrite x", "notes": []})
    assert calls == []
    assert state["route_used"] == "REFUSE"
    assert state["context"].is_empty()


def test_graph_and_vector_both_empty_refuses() -> None:
    pipe = _pipe("GRAPH", graph=GraphRetrieval(), passages=[])
    state = pipe.invoke({"question": "which x use y", "notes": []})
    assert state["route_used"] == "REFUSE"
    assert state["context"].is_empty()


def test_confidence_floor_downgrade_is_honoured() -> None:
    # router returns a low-confidence GRAPH -> route_question would floor to HYBRID;
    # here we hand the pipeline the already-floored decision.
    calls: list[str] = []
    pipe = compile_pipeline(
        router=lambda _q: _decision("HYBRID", conf=0.55),
        graph_fn=lambda _q: calls.append("graph") or GraphRetrieval(),
        vector_fn=lambda _q: calls.append("vector") or [_passage("v.md")],
    )
    state = pipe.invoke({"question": "ambiguous", "notes": []})
    assert calls == ["graph", "vector"]
    assert state["route_used"] == "HYBRID"
