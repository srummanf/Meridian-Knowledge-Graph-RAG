"""Phase 3.4: merge graph facts and vector passages into one labelled context.

rules.md §5.4 — for HYBRID (and for a route that fell back), run both retrievers,
concatenate, dedupe, and hand synthesis *both* labelled sets. Dedupe rules:

- **passages**: one per ``chunk_id`` (keep the best-scoring), then drop any whose
  text is a near-duplicate of one already kept (``SequenceMatcher`` ratio).
- **graph facts**: already deduped by sentence inside ``retrieve_graph``; here we
  just drop exact-text repeats that a fallback run might reintroduce.

``chunk_ids`` collects every source that contributed — the retrieved set the
citation validator checks against (rules.md §5.6). No LLM call.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from src.logging_config import get_logger
from src.models.answer import GraphFact, MergedContext, Passage

log = get_logger("merge")

NEAR_DUPLICATE_RATIO = 0.95  # texts this similar are treated as the same passage


def _dedupe_passages(passages: list[Passage]) -> list[Passage]:
    """Best passage per chunk_id, then drop near-duplicate bodies."""
    best: dict[str, Passage] = {}
    for passage in passages:
        current = best.get(passage.chunk_id)
        if current is None or passage.score < current.score:
            best[passage.chunk_id] = passage

    kept: list[Passage] = []
    for passage in sorted(best.values(), key=lambda p: p.score):
        if any(
            SequenceMatcher(None, passage.content, k.content).ratio()
            >= NEAR_DUPLICATE_RATIO
            for k in kept
        ):
            continue
        kept.append(passage)
    return kept


def _dedupe_facts(facts: list[GraphFact]) -> list[GraphFact]:
    seen: dict[str, GraphFact] = {}
    for fact in facts:
        seen.setdefault(fact.text, fact)
    return list(seen.values())


def merge(
    graph_facts: list[GraphFact] | None,
    passages: list[Passage] | None,
) -> MergedContext:
    """Combine and dedupe the two retrieval sides into one context object."""
    facts = _dedupe_facts(graph_facts or [])
    kept_passages = _dedupe_passages(passages or [])

    chunk_ids: list[str] = []
    for source in (
        *(f.source_chunk_id for f in facts),
        *(p.chunk_id for p in kept_passages),
    ):
        if source and source not in chunk_ids:
            chunk_ids.append(source)

    log.info(
        "merge: %d graph facts, %d passages -> %d sources",
        len(facts),
        len(kept_passages),
        len(chunk_ids),
    )
    return MergedContext(
        graph_facts=facts, passages=kept_passages, chunk_ids=chunk_ids
    )


def labelled_context(context: MergedContext) -> str:
    """Render the context under ``GRAPH FACTS`` / ``RETRIEVED PASSAGES`` headers.

    rules.md §5.7 — synthesis and the reader must be able to tell the two sources
    apart. Each line/passage is tagged with its ``chunk_id`` so the model cites
    from the retrieved set.
    """
    blocks: list[str] = []
    if context.graph_facts:
        lines = [
            f"- {fact.text} [{fact.source_chunk_id}]"
            if fact.source_chunk_id
            else f"- {fact.text}"
            for fact in context.graph_facts
        ]
        blocks.append("GRAPH FACTS\n" + "\n".join(lines))
    if context.passages:
        chunks = [
            f"[{p.chunk_id}] ({p.document})\n{p.content}" for p in context.passages
        ]
        blocks.append("RETRIEVED PASSAGES\n" + "\n\n".join(chunks))
    return "\n\n".join(blocks)
