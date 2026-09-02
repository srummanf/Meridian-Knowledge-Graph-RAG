"""Phase 4.1: synthesise a cited answer from the merged context.

One ``chat_model.with_structured_output(SynthesisResult)`` call. The context is
handed to the model under ``GRAPH FACTS`` / ``RETRIEVED PASSAGES`` headers
(``merge.labelled_context``), and the model must ground **every** claim in a
citation whose ``chunk_id`` is one it was shown (rules.md §5.6, §5.7). The
citation *validator* (Phase 4.2) is what enforces that afterwards — here we only
ask for it and assemble the :class:`GroundedAnswer`.

``synthesize`` is never called on a REFUSE — the pipeline ends at the refuse node
and the API turns that into a 422.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.config import chat_model
from src.logging_config import get_logger
from src.models.answer import Citation, GroundedAnswer, MergedContext, RoutingUsed
from src.pipeline.merge import labelled_context

if TYPE_CHECKING:
    from langchain_core.runnables import Runnable

log = get_logger("synthesize")

_NO_ANSWER = "The retrieved context does not contain enough information to answer this question."


class SynthesisResult(BaseModel):
    """The model's cited answer — assembled into a GroundedAnswer by the node."""

    answer: str = Field(min_length=1)
    citations: list[Citation] = Field(default_factory=list)


_SYSTEM_PROMPT = f"""\
You answer questions about Meridian's internal architecture from the context
below — nothing else. The context has two labelled sections: GRAPH FACTS (one
relationship per line, each tagged with its source chunk id in [brackets]) and
RETRIEVED PASSAGES (each prefixed with its source chunk id in [brackets]).

Rules:
- Use ONLY facts stated in the context. Do not add outside knowledge.
- Every claim in your answer must be backed by a citation. Each citation has:
  claim (the sentence it supports), chunk_id (copied EXACTLY from a [bracket] in
  the context), and source_type ("GRAPH" if it came from a GRAPH FACTS line,
  "VECTOR" if from a passage).
- Prefer the GRAPH FACTS for "which/how many/what depends on" questions; use the
  passages for definitions and detail.
- Be concise and direct. Lead with the answer. If the question asks "how many",
  state the number.
- If the context does not answer the question, set answer to exactly:
  "{_NO_ANSWER}" and return no citations.
"""


def _prompt(
    question: str, context: MergedContext, allowed_chunk_ids: set[str] | None
) -> list:
    body = labelled_context(context)
    human = f"CONTEXT\n{body}\n\nQUESTION\n{question}"
    if allowed_chunk_ids:
        allowed = ", ".join(sorted(allowed_chunk_ids))
        human += (
            f"\n\nA previous attempt cited a source that was not in the context. "
            f"Cite ONLY from these chunk ids: {allowed}"
        )
    return [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=human)]


def synthesize(
    question: str,
    context: MergedContext,
    *,
    routing_used: RoutingUsed,
    model: Runnable | None = None,
    allowed_chunk_ids: set[str] | None = None,
) -> GroundedAnswer:
    """Produce a cited :class:`GroundedAnswer` for ``question`` from ``context``.

    ``allowed_chunk_ids`` adds an explicit cite-only-from allow-list to the
    prompt — the citation validator (Phase 4.2) sets it on its one retry.
    """
    if context.is_empty():
        return GroundedAnswer(
            question=question,
            answer=_NO_ANSWER,
            citations=[],
            routing_used=routing_used,
            latency_ms=0.0,
        )

    llm = model if model is not None else chat_model(SynthesisResult)
    started = time.perf_counter()
    result: SynthesisResult = llm.invoke(
        _prompt(question, context, allowed_chunk_ids)
    )
    latency_ms = (time.perf_counter() - started) * 1000

    log.info(
        "synthesize %r -> %d chars, %d citations (%.0fms)",
        question,
        len(result.answer),
        len(result.citations),
        latency_ms,
    )
    return GroundedAnswer(
        question=question,
        answer=result.answer,
        citations=result.citations,
        routing_used=routing_used,
        graph_paths=[fact.text for fact in context.graph_facts],
        vector_passages=[passage.chunk_id for passage in context.passages],
        latency_ms=latency_ms,
    )
