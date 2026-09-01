"""The Cypher template catalogues are complete and parameterised (no interpolation)."""

from __future__ import annotations

import re
from typing import get_args

from src.graph.queries import (
    _UPSERT_ENTITY,
    _UPSERT_REL,
    ENTITY_TEMPLATES,
    RELATIONSHIP_TEMPLATES,
)
from src.models.domain import EntityType, RelationType


def test_one_entity_template_per_type() -> None:
    assert set(ENTITY_TEMPLATES) == set(get_args(EntityType))
    assert len(ENTITY_TEMPLATES) == 11


def test_one_relationship_template_per_type() -> None:
    assert set(RELATIONSHIP_TEMPLATES) == set(get_args(RelationType))
    assert len(RELATIONSHIP_TEMPLATES) == 12


def test_entity_templates_merge_on_id_and_set_label() -> None:
    for label, template in ENTITY_TEMPLATES.items():
        assert "MERGE (e:Entity {id: $id})" in template
        assert f"SET e:`{label}`" in template
        assert "CREATE" not in template  # MERGE, never CREATE


def test_relationship_templates_key_on_source_chunk_id() -> None:
    for rel_type, template in RELATIONSHIP_TEMPLATES.items():
        assert "{source_chunk_id: $source_chunk_id}" in template
        assert f":{rel_type} " in template or f":`{rel_type}`" in template or rel_type == "HANDLES"


def test_handles_template_uses_a_concern_node() -> None:
    template = RELATIONSHIP_TEMPLATES["HANDLES"]
    assert "MERGE (c:Concern {id: $target_id})" in template
    assert "[r:HANDLES {source_chunk_id: $source_chunk_id}]->(c)" in template


def test_no_template_has_an_unfilled_placeholder() -> None:
    # after .format(), no bare {label}/{rel} braces should remain
    for template in (*ENTITY_TEMPLATES.values(), *RELATIONSHIP_TEMPLATES.values()):
        assert not re.search(r"\{[a-z_]+\}", template)


def test_templates_only_use_named_parameters() -> None:
    # every $token is a named param; there is no string interpolation of values
    for template in (*ENTITY_TEMPLATES.values(), *RELATIONSHIP_TEMPLATES.values()):
        for token in re.findall(r"\$(\w+)", template):
            assert token in {
                "id",
                "props",
                "source_id",
                "target_id",
                "target_name",
                "source_chunk_id",
                "evidence",
                "confidence",
            }


def test_raw_templates_are_format_strings() -> None:
    assert "{label}" in _UPSERT_ENTITY
    assert "{rel}" in _UPSERT_REL
