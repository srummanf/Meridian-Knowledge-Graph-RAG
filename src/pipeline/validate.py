"""Phase 4.2: citation validation — the last hand-written gate (rules.md §5.6).

Every ``chunk_id`` a synthesised answer cites must be in the *retrieved set*
(``MergedContext.chunk_ids``). The model has the ids in its prompt, so a miss is
either a typo or a hallucinated source — either way the claim is not grounded.

On a miss:

1. regenerate **once**, adding an explicit ``Cite ONLY from: [...]`` allow-list;
2. from whatever comes back, keep only the citations that are in the set;
3. attach a note recording what was dropped.

This is wired as the final node of the LangGraph pipeline (``pipeline/graph.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.logging_config import get_logger
from src.models.answer import Citation, GroundedAnswer, MergedContext
from src.pipeline.synthesize import synthesize

if TYPE_CHECKING:
    from langchain_core.runnables import Runnable

log = get_logger("validate")


def _invalid(citations: list[Citation], retrieved: set[str]) -> list[Citation]:
    return [c for c in citations if c.chunk_id not in retrieved]


def validate_answer(
    answer: GroundedAnswer,
    context: MergedContext,
    *,
    question: str,
    model: Runnable | None = None,
) -> GroundedAnswer:
    """Return an answer whose every citation is in the retrieved set.

    Unchanged when all citations are already valid; otherwise regenerated once
    with an allow-list, then filtered to the valid citations with a note.
    """
    retrieved = set(context.chunk_ids)
    bad = _invalid(answer.citations, retrieved)
    if not bad:
        return answer

    log.info(
        "validate %r: %d/%d citations outside the retrieved set -> regenerate",
        question,
        len(bad),
        len(answer.citations),
    )
    retry = synthesize(
        question,
        context,
        routing_used=answer.routing_used,
        model=model,
        allowed_chunk_ids=retrieved,
    )

    kept = [c for c in retry.citations if c.chunk_id in retrieved]
    dropped = _invalid(retry.citations, retrieved)
    notes = list(retry.notes)
    if dropped:
        ids = ", ".join(sorted({c.chunk_id for c in dropped}))
        notes.append(
            f"{len(dropped)} citation(s) to sources outside the retrieved set "
            f"were removed after one regeneration ({ids})."
        )
        log.warning("validate %r: still %d invalid after retry", question, len(dropped))

    return retry.model_copy(update={"citations": kept, "notes": notes})
