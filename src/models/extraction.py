"""The schema handed to ``chat_model.with_structured_output(...)`` at ingest.

One :class:`ExtractionResult` per chunk. The LLM fills ``entities`` and
``relationships`` using :mod:`src.models.domain`; the ingest pipeline then stamps
``source_chunk_id`` on every row and applies the validation rules in
``data/SCHEMA.md`` §4 (enum, evidence-substring, property-subset, confidence
floor).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.models.domain import Entity, Relationship


class ExtractionResult(BaseModel):
    """Structured-output target for a single chunk's extraction."""

    entities: list[Entity] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
