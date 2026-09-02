"""Vector-only RAG baseline (Phase 5.1) — the control for the benchmark.

The *same* pipeline as production with the router pinned to VECTOR: every
question goes ``retrieve_vector → merge → synthesize → validate`` and the graph
is never touched. Holding everything else constant (same chunks, same local
embeddings, same synthesis prompt, same citation validator) isolates the one
variable the benchmark is about — *what does the knowledge graph add*.

A REFUSE-worthy question still reaches synthesis here; the synthesis prompt's
"if the context does not answer, say so" guard is the baseline's only defence
against answering out of scope — which is part of what Phase 5.2 measures.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.logging_config import get_logger
from src.models.routing import RoutingDecision
from src.pipeline.graph import PipelineState, compile_answer_pipeline

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

log = get_logger("baseline.vector_only")

_FORCED_VECTOR = RoutingDecision(
    route="VECTOR",
    confidence=1.0,
    reasoning="baseline: router pinned to VECTOR",
    entities_detected=[],
)


def _force_vector(_question: str) -> RoutingDecision:
    return _FORCED_VECTOR


_PIPELINE: CompiledStateGraph | None = None


def answer_vector_only(question: str) -> PipelineState:
    """Answer ``question`` with the graph disabled (singleton compiled pipeline)."""
    global _PIPELINE
    if _PIPELINE is None:
        _PIPELINE = compile_answer_pipeline(router=_force_vector)
    return _PIPELINE.invoke({"question": question, "notes": []})
