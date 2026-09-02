"""Answer-side models: retrieved passages, citations, and the final answer.

``GroundedAnswer`` is what ``POST /query`` returns (architecture.md §5). Every
claim in ``answer`` must be backed by a :class:`Citation` whose ``chunk_id`` is
in the retrieved set — enforced by ``src/pipeline/validate.py`` (Phase 4.2).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SourceType = Literal["VECTOR", "GRAPH"]
RoutingUsed = Literal["VECTOR", "GRAPH", "HYBRID"]


class Passage(BaseModel):
    """A chunk returned by vector retrieval (architecture.md §4 pipeline state)."""

    chunk_id: str = Field(min_length=1)
    document: str = Field(min_length=1)
    content: str = Field(min_length=1)
    score: float


class GraphFact(BaseModel):
    """One relationship from graph retrieval, rendered as a sentence.

    The vector-side counterpart is :class:`Passage`. ``source_chunk_id`` is the
    chunk the edge was extracted from — synthesis cites it like any passage.
    """

    text: str = Field(min_length=1)
    source_chunk_id: str = ""
    evidence: str = ""


class MergedContext(BaseModel):
    """Graph facts + vector passages after dedupe — the input to synthesis.

    ``chunk_ids`` is the *retrieved set*: every source that contributed a fact or
    a passage. ``src/pipeline/validate.py`` (Phase 4.2) rejects any citation
    whose ``chunk_id`` is not in this list.
    """

    graph_facts: list[GraphFact] = Field(default_factory=list)
    passages: list[Passage] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.graph_facts and not self.passages


class Citation(BaseModel):
    """One claim tied to the source it came from."""

    claim: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    source_type: SourceType


class GroundedAnswer(BaseModel):
    """The cited answer to a single question."""

    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    citations: list[Citation] = Field(default_factory=list)
    routing_used: RoutingUsed
    graph_paths: list[str] = Field(default_factory=list)
    vector_passages: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)  # e.g. citation-validator actions
    latency_ms: float = Field(ge=0.0)
