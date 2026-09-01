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
    latency_ms: float = Field(ge=0.0)
