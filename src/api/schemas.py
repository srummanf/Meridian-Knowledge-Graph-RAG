"""Request / response bodies for the API (architecture.md §5).

The 200 body is :class:`~src.models.answer.GroundedAnswer` as-is. This module
adds the request shape and the non-200 error bodies.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

QUESTION_MAX_CHARS = 1000


class QueryRequest(BaseModel):
    """``POST /query`` input. ``top_k`` / ``max_hops`` are accepted for forward
    compatibility; the pipeline currently uses its own defaults (k=5, ≤3 hops)."""

    question: str = Field(min_length=1, max_length=QUESTION_MAX_CHARS)
    top_k: int = Field(default=5, ge=1, le=20)
    max_hops: int = Field(default=3, ge=1, le=5)


class OutOfScope(BaseModel):
    """422 — the router refused the question."""

    error: str = "out_of_scope"
    reason: str
    message: str


class ErrorBody(BaseModel):
    """400 / 503."""

    error: str
    message: str


class HealthResponse(BaseModel):
    status: str
    neo4j: str
    postgres: str
