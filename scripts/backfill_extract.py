"""Seed the LLM cache for chunks Groq's free tier structurally cannot serve.

Groq's free tier rejects any single request over its per-minute token limit
(``413 Request too large``); a few of the larger chunks clear that ceiling once
the JSON schema and output reservation are added, and no wait fixes it.

This script extracts those chunks with **Gemini** via the normal
``extract_chunk`` retry loop, then writes the validated result into
``cache/llm.db`` as the response for the *first-attempt* prompt under the Google
model's cache key. The normal ``ingest_corpus.py`` run (Groq-primary, Google
fallback) then gets a clean first-attempt cache hit on the Google leg for these
chunks — no live calls, fully idempotent.

    python scripts/backfill_extract.py                 # the known oversized set
    python scripts/backfill_extract.py teams/data-team.md ...

Safe to re-run: it never deletes a cache row, and only writes a row it has a
validated ``ExtractionResult`` for.
"""

from __future__ import annotations

import sqlite3
import sys

from langchain_core.load import dumps
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration

from src.config import CACHE_DIR, configure_llm_cache, extract_model
from src.ingest.chunk import Chunk, chunk_corpus
from src.ingest.extract import _format_chunk, _system_prompt, extract_chunk
from src.logging_config import configure_logging, get_logger
from src.models.extraction import ExtractionResult
from src.utils.errors import ExtractionError

configure_logging()
log = get_logger("backfill")

DEFAULT_TARGETS = [
    "services/user-service.md#overview",
    "services/user-service.md#security",
    "teams/data-team.md",
    "teams/growth-team.md",
    "teams/payments-team.md",
    "teams/platform-team.md",
    "vulnerabilities/cve-2021-44228-log4shell.md",
    "vulnerabilities/cve-2024-0985-postgresql.md",
]

_GOOGLE_MARKER = "%ChatGoogleGenerativeAI%"


def _first_attempt_key(chunk: Chunk) -> str:
    return dumps(
        [
            SystemMessage(content=_system_prompt()),
            HumanMessage(content=_format_chunk(chunk)),
        ]
    )


def _google_llm_string(conn: sqlite3.Connection) -> str | None:
    """Any existing Google cache row's key — identical across chunks (same schema)."""
    row = conn.execute(
        "SELECT llm FROM full_llm_cache WHERE llm LIKE ? LIMIT 1", (_GOOGLE_MARKER,)
    ).fetchone()
    return row[0] if row else None


def _seed(chunk: Chunk, result: ExtractionResult) -> str:
    payload = result.model_dump_json()
    # SQLiteCache stores ONE row per generation: response = dumps(<single gen>).
    response = dumps(ChatGeneration(message=AIMessage(content=payload), text=payload))
    key = _first_attempt_key(chunk)
    with sqlite3.connect(CACHE_DIR / "llm.db") as conn:
        row = conn.execute(
            "SELECT llm FROM full_llm_cache WHERE prompt = ? AND llm LIKE ?",
            (key, _GOOGLE_MARKER),
        ).fetchone()
        llm = row[0] if row else _google_llm_string(conn)
        if llm is None:
            return "skipped (no Google key to match)"
        conn.execute(
            "INSERT INTO full_llm_cache (prompt, llm, idx, response) VALUES (?, ?, 0, ?) "
            "ON CONFLICT(prompt, llm, idx) DO UPDATE SET response = excluded.response",
            (key, llm, response),
        )
    return "updated" if row else "inserted"


def main(argv: list[str] | None = None) -> int:
    targets = set(argv if argv is not None else sys.argv[1:] or DEFAULT_TARGETS)
    configure_llm_cache()
    google = extract_model(ExtractionResult, only="google")

    chunks = [c for c in chunk_corpus() if c.chunk_id in targets]
    missing = targets - {c.chunk_id for c in chunks}
    if missing:
        log.error("unknown chunk ids: %s", sorted(missing))
        return 2

    failed: list[str] = []
    for chunk in chunks:
        try:
            result = extract_chunk(chunk, model=google)
        except ExtractionError as exc:
            log.error("giving up on %s: %s", exc.chunk_id, "; ".join(exc.errors))
            failed.append(chunk.chunk_id)
            continue
        action = _seed(chunk, result)
        log.info(
            "%s: %d entities, %d relationships -> %s",
            chunk.chunk_id,
            len(result.entities),
            len(result.relationships),
            action,
        )

    print(f"\nseeded {len(chunks) - len(failed)}/{len(chunks)} chunks")
    if failed:
        print(f"failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
