"""Phase 3.4: merge + labelled context. Pure functions, no DB, no LLM."""

from __future__ import annotations

from src.models.answer import GraphFact, Passage
from src.pipeline.merge import labelled_context, merge


def _passage(chunk_id: str, content: str = "body", score: float = 0.1) -> Passage:
    return Passage(chunk_id=chunk_id, document=chunk_id, content=content, score=score)


def test_merge_keeps_best_scoring_passage_per_chunk() -> None:
    context = merge(
        None,
        [_passage("a.md", "v1", 0.4), _passage("a.md", "v2", 0.2), _passage("b.md")],
    )
    assert {p.chunk_id for p in context.passages} == {"a.md", "b.md"}
    kept_a = next(p for p in context.passages if p.chunk_id == "a.md")
    assert kept_a.score == 0.2


def test_merge_drops_near_duplicate_passage_bodies() -> None:
    body = "The Auth Service issues JWT access tokens via the OAuth2 flow."
    context = merge(
        None,
        [_passage("a.md", body, 0.1), _passage("b.md", body + " ", 0.2)],
    )
    assert len(context.passages) == 1
    assert context.passages[0].chunk_id == "a.md"


def test_merge_dedupes_repeated_graph_facts() -> None:
    facts = [
        GraphFact(text="A uses B.", source_chunk_id="one.md"),
        GraphFact(text="A uses B.", source_chunk_id="two.md"),
    ]
    context = merge(facts, None)
    assert len(context.graph_facts) == 1
    assert context.graph_facts[0].source_chunk_id == "one.md"


def test_chunk_ids_union_graph_then_vector_in_order() -> None:
    facts = [GraphFact(text="A uses B.", source_chunk_id="g.md")]
    context = merge(facts, [_passage("v.md"), _passage("g.md")])
    assert context.chunk_ids == ["g.md", "v.md"]


def test_empty_merge_is_empty() -> None:
    assert merge(None, None).is_empty()
    assert merge([], []).is_empty()


def test_labelled_context_has_both_headers_and_cites_each_line() -> None:
    facts = [GraphFact(text="A uses B.", source_chunk_id="g.md")]
    text = labelled_context(merge(facts, [_passage("v.md", "passage text")]))
    assert "GRAPH FACTS" in text
    assert "RETRIEVED PASSAGES" in text
    assert "[g.md]" in text
    assert "[v.md]" in text


def test_labelled_context_omits_an_absent_side() -> None:
    text = labelled_context(merge([GraphFact(text="A uses B.")], None))
    assert "GRAPH FACTS" in text
    assert "RETRIEVED PASSAGES" not in text
