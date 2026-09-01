"""Per-chunk extractions -> one clean, deduplicated graph.

Resolution is deterministic (rules.md §3.5): the same extractions always produce
the same entities and edges, so the Neo4j ``MERGE`` load is idempotent.

Steps (architecture.md §6):

1. **Normalise** each entity name — strip a leading article, peel a trailing
   version into ``properties.version``, then look it up in the ``ONTOLOGY.md`` §3
   alias table. A hit replaces both the name *and* the type (the table is the
   source of truth); a miss keeps the LLM's name and type, cleaned.
2. **Recompute** the deterministic id from the resolved ``(type, name)``.
3. **Merge** entities that now share an id (union aliases, keep the
   highest-confidence chunk as the primary source).
4. **Re-point** every relationship endpoint at a resolved entity by name, then
   merge edges that share ``(source, type, target, source_chunk_id)`` — the same
   key Neo4j uses, so parallel edges from different chunks are kept on purpose.
"""

from __future__ import annotations

import functools
import re
from typing import get_args

from src.config import DATA_DIR
from src.models.domain import DataConcern, Entity, Relationship, make_entity_id, slugify
from src.models.extraction import ExtractionResult

_ARTICLES = ("the ", "a ", "an ")
_TRAILING_VERSION = re.compile(r"\s+v?\d+(?:\.\d+)*$")
_WS = re.compile(r"\s+")
_CONCERNS: tuple[str, ...] = get_args(DataConcern)


def _key(name: str) -> str:
    """Comparison key: lowercase, no leading article, collapsed whitespace."""
    text = _WS.sub(" ", name).strip().lower()
    for article in _ARTICLES:
        if text.startswith(article):
            return text[len(article) :]
    return text


def _strip_article(name: str) -> str:
    lowered = name.lower()
    for article in _ARTICLES:
        if lowered.startswith(article):
            return name[len(article) :]
    return name


def _split_version(name: str) -> tuple[str, str | None]:
    match = _TRAILING_VERSION.search(name)
    if not match:
        return name, None
    return name[: match.start()].strip(), match.group().strip().lstrip("v")


@functools.lru_cache(maxsize=1)
def alias_index() -> dict[str, tuple[str, str]]:
    """``_key(name) -> (canonical_name, entity_type)`` from ``ONTOLOGY.md`` §3."""
    text = (DATA_DIR / "ONTOLOGY.md").read_text(encoding="utf-8")
    start = text.index("## 3.")
    section = text[start : text.index("## 4.", start)]

    index: dict[str, tuple[str, str]] = {}
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 3 or cells[0] in ("Canonical name", "") or set(cells[0]) <= {"-"}:
            continue
        canonical, entity_type, aliases = cells
        names = [canonical]
        if aliases and aliases != "—":
            names.extend(a.strip() for a in aliases.split(","))
        for name in names:
            index[_key(name)] = (canonical, entity_type)
    return index


def resolve_entity(entity: Entity) -> Entity:
    """Return a canonicalised copy of ``entity`` with a recomputed id."""
    raw = _strip_article(entity.canonical_name).strip()

    hit = alias_index().get(_key(raw))
    version: str | None = None
    if hit is None:
        base, version = _split_version(raw)
        hit = alias_index().get(_key(base))
        raw = base if hit else raw

    if hit is not None:
        canonical, entity_type = hit
    else:
        canonical, entity_type = raw, entity.type

    properties = dict(entity.properties)
    if version:
        properties.setdefault("version", version)

    aliases = {a.strip() for a in entity.aliases if a.strip()}
    if entity.canonical_name.strip() and entity.canonical_name != canonical:
        aliases.add(entity.canonical_name.strip())

    return Entity(
        id=make_entity_id(entity_type, canonical),
        type=entity_type,
        canonical_name=canonical,
        aliases=sorted(aliases),
        properties=properties,
        confidence=entity.confidence,
        source_chunk_id=entity.source_chunk_id,
    )


def _merge_entities(entities: list[Entity]) -> list[Entity]:
    merged: dict[str, Entity] = {}
    for entity in entities:
        current = merged.get(entity.id)
        if current is None:
            merged[entity.id] = entity
            continue
        keep_new = entity.confidence > current.confidence
        properties = dict(current.properties)
        for key, value in entity.properties.items():
            properties.setdefault(key, value)
        merged[entity.id] = Entity(
            id=entity.id,
            type=current.type,
            canonical_name=current.canonical_name,
            aliases=sorted(set(current.aliases) | set(entity.aliases)),
            properties=properties,
            confidence=max(current.confidence, entity.confidence),
            source_chunk_id=(
                entity.source_chunk_id if keep_new else current.source_chunk_id
            ),
        )
    return list(merged.values())


def _endpoint_index(entities: list[Entity]) -> dict[str, str]:
    """``_key(name) -> entity id`` over the alias table plus resolved entities.

    Every §3 alias key is seeded first; resolved entities then win on conflict.
    """
    index: dict[str, str] = {
        key: make_entity_id(entity_type, canonical)
        for key, (canonical, entity_type) in alias_index().items()
    }
    for entity in entities:
        for name in (entity.canonical_name, *entity.aliases):
            index[_key(name)] = entity.id
    return index


def _concern_ref(name: str) -> tuple[str, str]:
    """Map a ``HANDLES`` target string onto the controlled vocabulary."""
    for concern in _CONCERNS:
        if concern.lower() == name.strip().lower():
            return f"concern:{slugify(concern)}", concern
    return f"concern:{slugify(name)}", name.strip()


def _resolve_endpoint(
    name: str, fallback_id: str, index: dict[str, str]
) -> tuple[str, str]:
    cleaned = _strip_article(name).strip()
    base, _ = _split_version(cleaned)
    for candidate in (cleaned, base):
        entity_id = index.get(_key(candidate))
        if entity_id:
            return entity_id, candidate
    return fallback_id, cleaned


def resolve_relationship(
    rel: Relationship, index: dict[str, str]
) -> Relationship | None:
    """Re-point a relationship at resolved entities. ``None`` if it self-loops."""
    source_id, source_name = _resolve_endpoint(rel.source_name, rel.source_id, index)

    if rel.type == "HANDLES":
        target_id, target_name = _concern_ref(rel.target_name)
    else:
        target_id, target_name = _resolve_endpoint(
            rel.target_name, rel.target_id, index
        )

    if source_id == target_id:
        return None

    if rel.type == "ALTERNATIVE_TO" and source_id > target_id:
        source_id, target_id = target_id, source_id
        source_name, target_name = target_name, source_name

    return Relationship(
        source_id=source_id,
        source_name=source_name,
        type=rel.type,
        target_id=target_id,
        target_name=target_name,
        properties=dict(rel.properties),
        confidence=rel.confidence,
        evidence=rel.evidence,
        source_chunk_id=rel.source_chunk_id,
    )


def _merge_relationships(relationships: list[Relationship]) -> list[Relationship]:
    merged: dict[tuple[str, str, str, str], Relationship] = {}
    for rel in relationships:
        key = (rel.source_id, rel.type, rel.target_id, rel.source_chunk_id)
        current = merged.get(key)
        if current is None or rel.confidence > current.confidence:
            merged[key] = rel
    return list(merged.values())


def resolve(
    results: list[ExtractionResult],
) -> tuple[list[Entity], list[Relationship]]:
    """Collapse per-chunk extractions into the deduplicated graph to load."""
    entities = _merge_entities(
        [resolve_entity(e) for result in results for e in result.entities]
    )
    index = _endpoint_index(entities)
    relationships = _merge_relationships(
        [
            resolved
            for result in results
            for rel in result.relationships
            if (resolved := resolve_relationship(rel, index)) is not None
        ]
    )
    return entities, relationships
