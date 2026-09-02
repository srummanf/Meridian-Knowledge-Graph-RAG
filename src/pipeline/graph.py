"""The query pipeline as a LangGraph ``StateGraph`` (rules.md §2.4).

    route ─┬─ REFUSE ──────────────────────────────────────► refuse ─► END
           ├─ VECTOR ──────────────► retrieve_vector ─┐
           └─ GRAPH / HYBRID ─► retrieve_graph ─┬─────┤
                                                │     ▼
                    (graph empty, or HYBRID) ───┘   merge ─► [synthesize ─► validate ─►] END
                                                      ▲
              retrieve_vector ─(has results)──────────┘
                             └─(nothing anywhere)─► refuse ─► END

Every node is a plain ``(state) -> partial state`` function. Conditional edges do
the routing and the two fallbacks: **graph empty → vector**, and **vector empty
(with nothing from the graph) → REFUSE**.

- ``compile_pipeline`` (Phase 3.4) is the **retrieval** graph — ends at ``merge``.
  The retrieval callables are injectable so tests use fakes.
- ``compile_answer_pipeline`` (Phase 4) appends ``synthesize`` → ``validate``.
  ``answer_question`` is its singleton entry point.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from src.logging_config import get_logger
from src.models.answer import GroundedAnswer, MergedContext, Passage, RoutingUsed
from src.models.routing import RoutingDecision
from src.pipeline.merge import merge
from src.pipeline.retrieve_graph import GraphRetrieval, retrieve_graph
from src.pipeline.retrieve_vector import retrieve_vector
from src.pipeline.router import route_question
from src.pipeline.synthesize import synthesize
from src.pipeline.validate import validate_answer

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

log = get_logger("pipeline")

RouterFn = Callable[[str], RoutingDecision]
GraphFn = Callable[[str], GraphRetrieval]
VectorFn = Callable[[str], list[Passage]]
SynthesizeFn = Callable[[str, MergedContext, RoutingUsed], GroundedAnswer]
ValidateFn = Callable[[GroundedAnswer, MergedContext, str], GroundedAnswer]


def _default_synthesize(
    question: str, context: MergedContext, routing_used: RoutingUsed
) -> GroundedAnswer:
    return synthesize(question, context, routing_used=routing_used)


def _default_validate(
    answer: GroundedAnswer, context: MergedContext, question: str
) -> GroundedAnswer:
    return validate_answer(answer, context, question=question)


class PipelineState(TypedDict, total=False):
    """Everything the pipeline accumulates for one question."""

    question: str
    decision: RoutingDecision
    route_used: Literal["VECTOR", "GRAPH", "HYBRID", "REFUSE"]
    graph: GraphRetrieval
    passages: list[Passage]
    context: MergedContext
    answer: GroundedAnswer
    notes: list[str]


def _has_graph_results(state: PipelineState) -> bool:
    graph = state.get("graph")
    return bool(graph and graph.facts)


def _note(state: PipelineState, message: str) -> list[str]:
    return [*state.get("notes", []), message]


def compile_pipeline(
    *,
    router: RouterFn = route_question,
    graph_fn: GraphFn = retrieve_graph,
    vector_fn: VectorFn = retrieve_vector,
) -> CompiledStateGraph:
    """Build and compile the query ``StateGraph``."""

    def route(state: PipelineState) -> PipelineState:
        decision = router(state["question"])
        return {"decision": decision, "route_used": decision.route}

    def retrieve_graph_node(state: PipelineState) -> PipelineState:
        return {"graph": graph_fn(state["question"])}

    def retrieve_vector_node(state: PipelineState) -> PipelineState:
        return {"passages": vector_fn(state["question"])}

    def merge_node(state: PipelineState) -> PipelineState:
        graph = state.get("graph")
        context = merge(graph.facts if graph else None, state.get("passages"))
        out: PipelineState = {"context": context}
        if state["route_used"] == "GRAPH" and not _has_graph_results(state):
            out["notes"] = _note(state, "graph empty; answered from vector fallback")
        return out

    def refuse_node(state: PipelineState) -> PipelineState:
        return {
            "route_used": "REFUSE",
            "context": MergedContext(),
            "notes": _note(state, "refused: nothing retrieved for the question"),
        }

    def from_route(state: PipelineState) -> str:
        route_used = state["route_used"]
        if route_used == "REFUSE":
            return "refuse"
        if route_used == "VECTOR":
            return "retrieve_vector"
        return "retrieve_graph"  # GRAPH, HYBRID

    def after_graph(state: PipelineState) -> str:
        # HYBRID always needs vector too; a GRAPH miss falls back to vector.
        if state["route_used"] == "HYBRID" or not _has_graph_results(state):
            return "retrieve_vector"
        return "merge"

    def after_vector(state: PipelineState) -> str:
        if state.get("passages") or _has_graph_results(state):
            return "merge"
        return "refuse"

    builder = StateGraph(PipelineState)
    builder.add_node("route", route)
    builder.add_node("retrieve_graph", retrieve_graph_node)
    builder.add_node("retrieve_vector", retrieve_vector_node)
    builder.add_node("merge", merge_node)
    builder.add_node("refuse", refuse_node)

    builder.add_edge(START, "route")
    builder.add_conditional_edges(
        "route", from_route, ["retrieve_graph", "retrieve_vector", "refuse"]
    )
    builder.add_conditional_edges(
        "retrieve_graph", after_graph, ["retrieve_vector", "merge"]
    )
    builder.add_conditional_edges("retrieve_vector", after_vector, ["merge", "refuse"])
    builder.add_edge("merge", END)
    builder.add_edge("refuse", END)
    return builder.compile()


def compile_answer_pipeline(
    *,
    router: RouterFn = route_question,
    graph_fn: GraphFn = retrieve_graph,
    vector_fn: VectorFn = retrieve_vector,
    synthesize_fn: SynthesizeFn = _default_synthesize,
    validate_fn: ValidateFn = _default_validate,
) -> CompiledStateGraph:
    """The full pipeline: retrieval, then ``synthesize`` → ``validate``.

    A REFUSE routes straight to ``refuse`` and never reaches synthesis — the API
    turns ``route_used == "REFUSE"`` into a 422.
    """

    def synthesize_node(state: PipelineState) -> PipelineState:
        answer = synthesize_fn(
            state["question"], state["context"], state["route_used"]
        )
        return {"answer": answer}

    def validate_node(state: PipelineState) -> PipelineState:
        checked = validate_fn(state["answer"], state["context"], state["question"])
        merged_notes = [*state.get("notes", []), *checked.notes]
        return {"answer": checked.model_copy(update={"notes": merged_notes})}

    builder = StateGraph(PipelineState)
    retrieval = compile_pipeline(
        router=router, graph_fn=graph_fn, vector_fn=vector_fn
    )
    builder.add_node("retrieve", retrieval)
    builder.add_node("synthesize", synthesize_node)
    builder.add_node("validate", validate_node)

    builder.add_edge(START, "retrieve")
    builder.add_conditional_edges(
        "retrieve",
        lambda s: END if s["route_used"] == "REFUSE" else "synthesize",
        ["synthesize", END],
    )
    builder.add_edge("synthesize", "validate")
    builder.add_edge("validate", END)
    return builder.compile()


_RETRIEVAL: CompiledStateGraph | None = None
_ANSWER: CompiledStateGraph | None = None


def run_pipeline(question: str) -> PipelineState:
    """Route + retrieve + merge for one question (singleton retrieval graph)."""
    global _RETRIEVAL
    if _RETRIEVAL is None:
        _RETRIEVAL = compile_pipeline()
    result: PipelineState = _RETRIEVAL.invoke({"question": question, "notes": []})
    log.info(
        "pipeline: %r -> %s (%d sources)",
        question,
        result.get("route_used"),
        len(result["context"].chunk_ids) if result.get("context") else 0,
    )
    return result


def answer_question(question: str) -> PipelineState:
    """Full pipeline through validated synthesis (singleton answer graph).

    Returns the final state — ``state["answer"]`` is the ``GroundedAnswer`` (absent
    when ``route_used == "REFUSE"``).
    """
    global _ANSWER
    if _ANSWER is None:
        _ANSWER = compile_answer_pipeline()
    return _ANSWER.invoke({"question": question, "notes": []})
