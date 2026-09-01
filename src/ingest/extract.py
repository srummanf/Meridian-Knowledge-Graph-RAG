"""Chunk -> :class:`ExtractionResult` via a structured-output LLM call.

Flow per chunk (architecture.md §6, rules.md §4.2):

1. Prompt the model with the ontology reference + the chunk, asking for
   ``ExtractionResult`` through ``with_structured_output`` (no hand JSON parsing).
2. Drop rows below :data:`~src.models.domain.CONFIDENCE_FLOOR` (not an error).
3. Validate: ``evidence`` is a whitespace-normalised substring of the chunk;
   relationship ``properties`` are a subset of what the type allows; relationship
   endpoints refer to entities extracted from the same chunk.
4. On validation failure, retry (up to :data:`MAX_RETRIES`) with the errors fed
   back to the model. After the budget is spent, raise :class:`ExtractionError`;
   ``extract_corpus`` catches that and records the chunk in ``failed`` instead of
   aborting the run.

LLM calls go through ``config.extract_model`` (its own Groq model, so the
token-heavy batch has a separate daily quota), which enables the SQLite cache —
a second run over the same chunks is free.
"""

from __future__ import annotations

import functools
import re
from typing import TYPE_CHECKING, NamedTuple

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from src.config import DATA_DIR, extract_model
from src.ingest.chunk import Chunk
from src.logging_config import get_logger
from src.models.domain import CONFIDENCE_FLOOR, RELATION_PROPERTY_KEYS
from src.models.extraction import ExtractionResult
from src.utils.errors import ExtractionError, LLMUnavailableError

if TYPE_CHECKING:
    from langchain_core.runnables import Runnable

log = get_logger("extract")

MAX_RETRIES = 3
_WS = re.compile(r"\s+")

_TASK_INSTRUCTIONS = """\
You extract a knowledge graph from one chunk of Meridian's internal architecture
wiki. Meridian is a fictional fintech (payments + merchant analytics).

Rules:
- Extract an entity only if the chunk names it. Extract a relationship only if a
  sentence in the chunk states it. Never infer transitive or implied links.
- Map every mention to its canonical name and type using the reference below.
  Apply the type-precedence list when a name could be more than one type.
- id = "<type_lowercase>:<slug(canonical_name)>" — slug lowercases and turns
  spaces/dots into "-". A version ("PostgreSQL 14.2") is not part of the name;
  put it in properties.version.
- evidence must be an exact, verbatim substring of the chunk text.
- confidence: 0.95-1.0 if stated in one sentence; 0.80-0.94 if paraphrased or
  spread across two sentences; below 0.80 do not extract it at all.
- A relationship's source_id and target_id must each be the id of an entity you
  also return for this chunk.
- properties: only the keys listed for that relationship type. Omit the rest.
- HANDLES: target_name is one of the controlled data-concern strings; target_id
  is "concern:<slug>". ALTERNATIVE_TO: emit one direction only.

Return an ExtractionResult. Leave source_chunk_id empty — the pipeline sets it.
"""


def _section_before(text: str, heading: str) -> str:
    idx = text.find(heading)
    return text[:idx].rstrip() if idx != -1 else text.rstrip()


def _section_from(text: str, heading: str) -> str:
    idx = text.find(heading)
    return text[idx:].rstrip() if idx != -1 else ""


@functools.lru_cache(maxsize=1)
def _ontology_reference() -> str:
    """Ontology §1-§3 (types, relationships, alias table) + the SCHEMA §5 example.

    Read from the corpus contract files so the prompt cannot drift from them.
    §4 (ID scheme) and §5 (confidence bands) are summarised in the task
    instructions already; §6-§7 are corpus targets, not extraction rules.
    """
    ontology = (DATA_DIR / "ONTOLOGY.md").read_text(encoding="utf-8")
    schema = (DATA_DIR / "SCHEMA.md").read_text(encoding="utf-8")
    ontology_core = _section_before(ontology, "\n## 4.")
    schema_example = _section_from(schema, "## 5.")
    return f"{ontology_core}\n\n---\n\n# Worked example\n\n{schema_example}"


@functools.lru_cache(maxsize=1)
def _system_prompt() -> str:
    return f"{_TASK_INSTRUCTIONS}\n\n---\n\n# Reference\n\n{_ontology_reference()}"


def _format_chunk(chunk: Chunk) -> str:
    return (
        f"chunk_id: {chunk.chunk_id}\n"
        f"document: {chunk.document}\n\n"
        f"--- CHUNK START ---\n{chunk.content}\n--- CHUNK END ---"
    )


def _norm(text: str) -> str:
    return _WS.sub(" ", text).strip().lower()


def _drop_low_confidence(result: ExtractionResult) -> tuple[ExtractionResult, int]:
    """Remove rows below the confidence floor. Returns (kept, dropped_count)."""
    entities = [e for e in result.entities if e.confidence >= CONFIDENCE_FLOOR]
    relationships = [r for r in result.relationships if r.confidence >= CONFIDENCE_FLOOR]
    dropped = (len(result.entities) - len(entities)) + (
        len(result.relationships) - len(relationships)
    )
    return ExtractionResult(entities=entities, relationships=relationships), dropped


def _validate(result: ExtractionResult, chunk: Chunk) -> list[str]:
    """Return human-readable validation errors; empty list means valid."""
    errors: list[str] = []
    haystack = _norm(chunk.content)
    entity_ids = {e.id for e in result.entities}

    for rel in result.relationships:
        if _norm(rel.evidence) not in haystack:
            errors.append(
                f"{rel.type} {rel.source_name}->{rel.target_name}: evidence is not a "
                f"substring of the chunk: {rel.evidence!r}"
            )
        allowed = RELATION_PROPERTY_KEYS.get(rel.type, frozenset())
        extra = sorted(set(rel.properties) - allowed)
        if extra:
            errors.append(
                f"{rel.type} {rel.source_name}->{rel.target_name}: properties {extra} "
                f"not allowed (allowed: {sorted(allowed) or 'none'})"
            )
        for role, ref in (("source_id", rel.source_id), ("target_id", rel.target_id)):
            if ref not in entity_ids and not ref.startswith("concern:"):
                errors.append(
                    f"{rel.type} {rel.source_name}->{rel.target_name}: {role} {ref!r} "
                    "is not an entity extracted from this chunk"
                )
    return errors


def _stamp(result: ExtractionResult, chunk_id: str) -> ExtractionResult:
    for row in (*result.entities, *result.relationships):
        row.source_chunk_id = chunk_id
    return result


def _feedback(errors: list[str], result: ExtractionResult) -> str:
    listed = "\n".join(f"- {e}" for e in errors)
    return (
        f"That extraction failed validation:\n{listed}\n\n"
        f"You returned:\n{result.model_dump_json(indent=2)}\n\n"
        "Return a corrected ExtractionResult: keep the valid rows, fix or drop the "
        "listed ones."
    )


_RATE_LIMIT_MARKERS = ("429", "rate limit", "rate_limit", "resource_exhausted", "quota")
_MALFORMED_MARKERS = (
    "failed to validate json",
    "failed_generation",
    "did not parse",
    "invalid json",
)


def _is_rate_limited(exc: Exception) -> bool:
    """True if ``exc`` looks like a provider throttling us (either provider)."""
    if getattr(exc, "status_code", None) == 429:
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _RATE_LIMIT_MARKERS)


def _is_malformed_output(exc: Exception) -> bool:
    """True if the model returned unparseable / schema-invalid structured output."""
    if isinstance(exc, ValidationError | OutputParserException):
        return True
    return any(marker in str(exc).lower() for marker in _MALFORMED_MARKERS)


def extract_chunk(
    chunk: Chunk,
    *,
    model: Runnable | None = None,
    max_retries: int = MAX_RETRIES,
) -> ExtractionResult:
    """Extract one chunk, retrying on validation failure. Raises on exhaustion."""
    llm = model if model is not None else extract_model(ExtractionResult)
    messages: list = [
        SystemMessage(content=_system_prompt()),
        HumanMessage(content=_format_chunk(chunk)),
    ]

    errors: list[str] = []
    for attempt in range(1, max_retries + 1):
        try:
            result: ExtractionResult = llm.invoke(messages)
        except Exception as exc:  # noqa: BLE001 - classify: rate-limit aborts, bad-JSON retries
            if _is_rate_limited(exc):
                raise
            if not _is_malformed_output(exc):
                raise
            errors = [f"response did not parse into ExtractionResult: {exc}"]
            log.warning(
                "%s: attempt %d/%d did not parse", chunk.chunk_id, attempt, max_retries
            )
            messages.append(
                HumanMessage(
                    content=(
                        f"Your last response could not be parsed ({exc}). Return a "
                        "valid ExtractionResult and nothing else."
                    )
                )
            )
            continue
        result, dropped = _drop_low_confidence(result)
        errors = _validate(result, chunk)
        if not errors:
            log.info(
                "%s: %d entities, %d relationships (%d below floor, attempt %d)",
                chunk.chunk_id,
                len(result.entities),
                len(result.relationships),
                dropped,
                attempt,
            )
            return _stamp(result, chunk.chunk_id)
        log.warning(
            "%s: attempt %d/%d failed validation (%d issues)",
            chunk.chunk_id,
            attempt,
            max_retries,
            len(errors),
        )
        messages.append(HumanMessage(content=_feedback(errors, result)))

    raise ExtractionError(chunk.chunk_id, errors)


class FailedChunk(NamedTuple):
    chunk_id: str
    errors: list[str]


def extract_corpus(
    chunks: list[Chunk], *, model: Runnable | None = None
) -> tuple[list[ExtractionResult], list[FailedChunk]]:
    """Extract every chunk. Failures are collected, not raised (rules.md §4.2)."""
    llm = model if model is not None else extract_model(ExtractionResult)
    results: list[ExtractionResult] = []
    failed: list[FailedChunk] = []

    for done, chunk in enumerate(chunks):
        try:
            results.append(extract_chunk(chunk, model=llm))
        except ExtractionError as exc:
            log.error("giving up on %s: %s", exc.chunk_id, "; ".join(exc.errors))
            failed.append(FailedChunk(exc.chunk_id, exc.errors))
        except Exception as exc:  # noqa: BLE001 - batch driver: classify, then continue or abort
            if _is_rate_limited(exc):
                raise LLMUnavailableError(
                    f"both providers throttled at {chunk.chunk_id} "
                    f"({done}/{len(chunks)} chunks done and cached — rerun to resume): {exc}"
                ) from exc
            log.error("unexpected error on %s: %s", chunk.chunk_id, exc)
            failed.append(FailedChunk(chunk.chunk_id, [f"{type(exc).__name__}: {exc}"]))

    log.info(
        "extraction done: %d/%d chunks ok, %d failed",
        len(results),
        len(chunks),
        len(failed),
    )
    return results, failed
