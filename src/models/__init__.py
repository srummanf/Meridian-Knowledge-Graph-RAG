"""Pydantic v2 models for the Meridian KG-RAG pipeline.

Vocabulary and the ID scheme come from ``data/ONTOLOGY.md``; the model shapes
come from ``architecture.md`` §4.
"""

from src.models.answer import (
    Citation,
    GraphFact,
    GroundedAnswer,
    MergedContext,
    Passage,
    RoutingUsed,
    SourceType,
)
from src.models.domain import (
    CONFIDENCE_FLOOR,
    RELATION_PROPERTY_KEYS,
    DataConcern,
    Entity,
    EntityType,
    Relationship,
    RelationType,
    make_entity_id,
    slugify,
)
from src.models.extraction import ExtractionResult
from src.models.routing import HYBRID_CONFIDENCE_FLOOR, Route, RoutingDecision

__all__ = [
    "CONFIDENCE_FLOOR",
    "HYBRID_CONFIDENCE_FLOOR",
    "RELATION_PROPERTY_KEYS",
    "Citation",
    "DataConcern",
    "Entity",
    "EntityType",
    "ExtractionResult",
    "GraphFact",
    "GroundedAnswer",
    "MergedContext",
    "Passage",
    "Relationship",
    "RelationType",
    "Route",
    "RoutingDecision",
    "RoutingUsed",
    "SourceType",
    "make_entity_id",
    "slugify",
]
