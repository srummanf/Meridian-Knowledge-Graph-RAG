"""Phase 1.3: extraction validation + retry (unit) and a live 3-doc run (gate).

Unit tests drive ``extract_chunk`` with a stub model so the validation and retry
logic is exercised with no API calls. The ``llm``-marked tests are the actual
gate: a clean run on three docs, and a cache hit on the second run.
"""

from __future__ import annotations

import pytest

from src.config import DATA_DIR
from src.ingest.chunk import Chunk, chunk_document
from src.ingest.extract import (
    FailedChunk,
    _drop_low_confidence,
    _stamp,
    _validate,
    extract_chunk,
    extract_corpus,
)
from src.models.extraction import ExtractionResult
from src.utils.errors import ExtractionError

CHUNK = Chunk(
    chunk_id="services/auth-service.md",
    document="services/auth-service.md",
    content=(
        "# Auth Service\n\n"
        "The Auth Service uses PostgreSQL as its credential store.\n"
        "The Auth Service depends on Django.\n"
    ),
)

AUTH = "service:auth-service"
PG = "database:postgresql"
DJANGO = "library:django"


def _entity(entity_id: str, name: str, etype: str, conf: float = 0.95) -> dict:
    return {
        "id": entity_id,
        "type": etype,
        "canonical_name": name,
        "confidence": conf,
    }


def _good_result() -> ExtractionResult:
    return ExtractionResult.model_validate(
        {
            "entities": [
                _entity(AUTH, "Auth Service", "Service"),
                _entity(PG, "PostgreSQL", "Database"),
                _entity(DJANGO, "Django", "Library"),
            ],
            "relationships": [
                {
                    "source_id": AUTH,
                    "source_name": "Auth Service",
                    "type": "USES",
                    "target_id": PG,
                    "target_name": "PostgreSQL",
                    "properties": {"purpose": "credential store"},
                    "confidence": 0.97,
                    "evidence": "The Auth Service uses PostgreSQL as its credential store.",
                },
                {
                    "source_id": AUTH,
                    "source_name": "Auth Service",
                    "type": "DEPENDS_ON",
                    "target_id": DJANGO,
                    "target_name": "Django",
                    "properties": {"optional": False},
                    "confidence": 0.96,
                    "evidence": "The Auth Service depends on Django.",
                },
            ],
        }
    )


class StubModel:
    """Stands in for a structured-output runnable; replays canned results."""

    def __init__(self, *responses: ExtractionResult | Exception) -> None:
        self._responses = list(responses)
        self.calls = 0

    def invoke(self, _messages: object) -> ExtractionResult:
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def test_validate_passes_clean_result() -> None:
    assert _validate(_good_result(), CHUNK) == []


def test_validate_flags_evidence_not_in_chunk() -> None:
    result = _good_result()
    result.relationships[0].evidence = "The Auth Service uses MySQL."
    errors = _validate(result, CHUNK)
    assert any("substring" in e for e in errors)


def test_validate_normalises_whitespace_in_evidence() -> None:
    result = _good_result()
    result.relationships[0].evidence = (
        "The   Auth Service uses\nPostgreSQL as its credential store."
    )
    assert _validate(result, CHUNK) == []


def test_validate_flags_disallowed_property() -> None:
    result = _good_result()
    result.relationships[1].properties = {"optional": False, "colour": "blue"}
    errors = _validate(result, CHUNK)
    assert any("not allowed" in e for e in errors)


def test_validate_flags_dangling_relationship_endpoint() -> None:
    result = _good_result()
    result.relationships[0].target_id = "database:mysql"
    errors = _validate(result, CHUNK)
    assert any("not an entity extracted from this chunk" in e for e in errors)


def test_validate_allows_concern_target_ids() -> None:
    # HANDLES targets are controlled strings with id "concern:<slug>", not entities.
    result = ExtractionResult.model_validate(
        {
            "entities": [_entity(AUTH, "Auth Service", "Service")],
            "relationships": [
                {
                    "source_id": AUTH,
                    "source_name": "Auth Service",
                    "type": "HANDLES",
                    "target_id": "concern:authentication-credentials",
                    "target_name": "authentication credentials",
                    "confidence": 0.95,
                    "evidence": "The Auth Service uses PostgreSQL as its credential store.",
                }
            ],
        }
    )
    assert _validate(result, CHUNK) == []


# --------------------------------------------------------------------------- #
# confidence floor + stamping
# --------------------------------------------------------------------------- #
def test_drop_low_confidence_removes_and_counts() -> None:
    result = _good_result()
    result.entities[2].confidence = 0.4
    result.relationships[1].confidence = 0.79
    kept, dropped = _drop_low_confidence(result)
    assert dropped == 2
    assert len(kept.entities) == 2
    assert len(kept.relationships) == 1


def test_stamp_sets_source_chunk_id() -> None:
    stamped = _stamp(_good_result(), "services/auth-service.md")
    assert all(e.source_chunk_id == "services/auth-service.md" for e in stamped.entities)
    assert all(
        r.source_chunk_id == "services/auth-service.md" for r in stamped.relationships
    )


# --------------------------------------------------------------------------- #
# retry loop
# --------------------------------------------------------------------------- #
def test_extract_chunk_succeeds_first_try() -> None:
    model = StubModel(_good_result())
    result = extract_chunk(CHUNK, model=model)
    assert model.calls == 1
    assert len(result.entities) == 3
    assert result.entities[0].source_chunk_id == CHUNK.chunk_id


def test_extract_chunk_retries_then_succeeds() -> None:
    bad = _good_result()
    bad.relationships[0].evidence = "not in the chunk at all"
    model = StubModel(bad, _good_result())
    result = extract_chunk(CHUNK, model=model)
    assert model.calls == 2
    assert len(result.relationships) == 2


def test_extract_chunk_recovers_from_unparseable_response() -> None:
    from langchain_core.exceptions import OutputParserException

    model = StubModel(OutputParserException("bad json"), _good_result())
    result = extract_chunk(CHUNK, model=model)
    assert model.calls == 2
    assert len(result.entities) == 3


def test_extract_chunk_raises_after_budget() -> None:
    bad = _good_result()
    bad.relationships[0].evidence = "never appears"
    model = StubModel(bad)
    with pytest.raises(ExtractionError) as exc:
        extract_chunk(CHUNK, model=model, max_retries=3)
    assert model.calls == 3
    assert exc.value.chunk_id == CHUNK.chunk_id
    assert exc.value.errors


def test_extract_corpus_collects_failures() -> None:
    good_chunk = CHUNK
    bad_chunk = Chunk(
        chunk_id="x.md", document="x.md", content="Nothing resolvable here."
    )
    bad = _good_result()
    bad.relationships[0].evidence = "not present"

    class Router:
        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, messages: object) -> ExtractionResult:
            self.calls += 1
            text = str(messages)
            if "x.md" in text:
                return bad
            return _good_result()

    results, failed = extract_corpus([good_chunk, bad_chunk], model=Router())
    assert len(results) == 1
    assert len(failed) == 1
    assert isinstance(failed[0], FailedChunk)
    assert failed[0].chunk_id == "x.md"


def test_extract_corpus_aborts_on_rate_limit_and_keeps_progress() -> None:
    from src.utils.errors import LLMUnavailableError

    class Throttled(Exception):
        status_code = 429

    chunk2 = Chunk(chunk_id="c2.md", document="c2.md", content="Auth Service uses Redis.")
    model = StubModel(_good_result(), Throttled("Error code: 429 - rate_limit_exceeded"))

    with pytest.raises(LLMUnavailableError) as exc:
        extract_corpus([CHUNK, chunk2], model=model)
    assert "1/2" in str(exc.value)  # first chunk done + cached before the abort


# --------------------------------------------------------------------------- #
# GATE — live LLM run
# --------------------------------------------------------------------------- #
GATE_DOCS = ("auth-service", "ledger-service", "payments-platform")


@pytest.mark.llm
@pytest.mark.parametrize("stem", GATE_DOCS)
def test_live_extraction_is_clean(stem: str) -> None:
    folder = "products" if stem == "payments-platform" else "services"
    chunks = chunk_document(DATA_DIR / folder / f"{stem}.md")
    for chunk in chunks:
        result = extract_chunk(chunk)
        assert result.entities, f"{chunk.chunk_id} produced no entities"
        assert _validate(result, chunk) == []
        assert all(e.source_chunk_id == chunk.chunk_id for e in result.entities)


@pytest.mark.llm
def test_live_extraction_second_run_hits_cache() -> None:
    import sqlite3

    from src.config import CACHE_DIR

    def cache_rows() -> int:
        with sqlite3.connect(CACHE_DIR / "llm.db") as conn:
            return conn.execute("SELECT count(*) FROM full_llm_cache").fetchone()[0]

    chunk = chunk_document(DATA_DIR / "services" / "ledger-service.md")[0]
    extract_chunk(chunk)  # warm the cache

    before = cache_rows()
    result = extract_chunk(chunk)
    after = cache_rows()

    assert after == before, "second run added cache rows => it hit the API again"
    assert result.entities
