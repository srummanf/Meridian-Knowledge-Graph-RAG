"""Core graph vocabulary and entity/relationship models.

Everything here derives from ``data/ONTOLOGY.md`` — the entity types (§1), the
relationship types (§2), the ``HANDLES`` data-concern vocabulary (§2 notes), the
confidence floor (§5), and the deterministic ID scheme (§4). If this module and
the ontology ever disagree, the ontology wins and this file is the bug.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Vocabulary (ONTOLOGY.md §1, §2)
# --------------------------------------------------------------------------- #
EntityType = Literal[
    "Product",
    "Service",
    "API",
    "Library",
    "Language",
    "Database",
    "CloudService",
    "Protocol",
    "SecurityMechanism",
    "Team",
    "Vulnerability",
]

RelationType = Literal[
    "PART_OF",
    "DEPENDS_ON",
    "USES",
    "EXPOSES",
    "CONSUMES",
    "COMMUNICATES_VIA",
    "SECURED_BY",
    "DEPLOYED_ON",
    "OWNED_BY",
    "HANDLES",
    "AFFECTS",
    "ALTERNATIVE_TO",
]

# ``HANDLES`` targets are controlled strings, not entities (ONTOLOGY.md §2 notes).
DataConcern = Literal[
    "PII",
    "PCI cardholder data",
    "financial records",
    "authentication credentials",
    "merchant business data",
]

# Property keys each relationship type is allowed to carry (ONTOLOGY.md §2).
# Extraction validation (Phase 1.3) checks a relationship's properties are a
# subset of its type's entry here.
RELATION_PROPERTY_KEYS: dict[str, frozenset[str]] = {
    "PART_OF": frozenset(),
    "DEPENDS_ON": frozenset({"optional", "version_constraint"}),
    "USES": frozenset({"purpose"}),
    "EXPOSES": frozenset(),
    "CONSUMES": frozenset(),
    "COMMUNICATES_VIA": frozenset({"primary"}),
    "SECURED_BY": frozenset(),
    "DEPLOYED_ON": frozenset(),
    "OWNED_BY": frozenset(),
    "HANDLES": frozenset(),
    "AFFECTS": frozenset({"affected_versions"}),
    "ALTERNATIVE_TO": frozenset(),
}

# ONTOLOGY.md §5: anything below this is dropped at ingest, not treated as an
# error. Kept here so the model layer and the ingest layer share one number.
CONFIDENCE_FLOOR = 0.80


# --------------------------------------------------------------------------- #
# Deterministic IDs (ONTOLOGY.md §4)
# --------------------------------------------------------------------------- #
_SEP_CHARS = re.compile(r"[\s.]+")          # spaces and dots become "-"
_DROP_CHARS = re.compile(r"[^a-z0-9-]")     # everything else non-alphanumeric goes
_DASH_RUN = re.compile(r"-{2,}")


def slugify(name: str) -> str:
    """Lowercase ``name``, turn spaces/dots into ``-``, strip other punctuation.

    ``"Auth Service"`` -> ``"auth-service"``; ``"CVE-2021-44228"`` unchanged;
    ``"AWS RDS"`` -> ``"aws-rds"``.
    """
    s = _SEP_CHARS.sub("-", name.strip().lower())
    s = _DROP_CHARS.sub("", s)
    return _DASH_RUN.sub("-", s).strip("-")


def make_entity_id(entity_type: str, canonical_name: str) -> str:
    """Build the deterministic ``"<type_lower>:<slug(name)>"`` id.

    ``make_entity_id("SecurityMechanism", "OAuth2") == "securitymechanism:oauth2"``.
    """
    return f"{entity_type.lower()}:{slugify(canonical_name)}"


# --------------------------------------------------------------------------- #
# Models (architecture.md §4)
# --------------------------------------------------------------------------- #
class Entity(BaseModel):
    """One node. ``id`` is deterministic (see :func:`make_entity_id`)."""

    id: str = Field(min_length=1)
    type: EntityType
    canonical_name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    # Set by the ingest pipeline from the chunk being processed, not by the LLM
    # (SCHEMA.md §2). Empty until then.
    source_chunk_id: str = ""


class Relationship(BaseModel):
    """One directed edge. ``evidence`` is an exact substring of the chunk."""

    source_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    type: RelationType
    target_id: str = Field(min_length=1)
    target_name: str = Field(min_length=1)
    properties: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = Field(min_length=1)
    # Added by the ingest pipeline, not the LLM (SCHEMA.md §3).
    source_chunk_id: str = ""
