"""Router output schema (architecture.md §4, rules.md §5.1).

The router classifies a question into one of four routes. The
``confidence < HYBRID_CONFIDENCE_FLOOR -> HYBRID`` rule lives in
``src/pipeline/router.py`` (Phase 3.1); the threshold constant lives here next to
the model it applies to.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Route = Literal["VECTOR", "GRAPH", "HYBRID", "REFUSE"]

# rules.md §5.1: a low-confidence classification is downgraded to HYBRID rather
# than trusted.
HYBRID_CONFIDENCE_FLOOR = 0.70


class RoutingDecision(BaseModel):
    """How a single question should be answered."""

    route: Route
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1)
    entities_detected: list[str] = Field(default_factory=list)
