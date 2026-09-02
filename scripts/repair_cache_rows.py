"""One-off: drop malformed rows from cached extraction responses.

Three chunks were extracted on 2026-09-02 while both free-tier providers were
being exhausted; one of them (`services/user-service.md#overview`) has a single
relationship in its cached response that is missing the required `confidence` /
`evidence` fields. The structured-output parser rejects the whole response, so
`extract_chunk` falls through to a live retry every ingest.

This rewrites the offending cache row(s) in place with the malformed
relationship objects removed — the 15 valid entities and 15 valid relationships
are kept. Prompt + llm_string (the cache key) are untouched; only `response`
changes. A backup of each original row is written next to the DB.

    python scripts/repair_cache_rows.py            # dry run
    python scripts/repair_cache_rows.py --write

Idempotent: a second run finds nothing malformed and makes no change.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime

from langchain_core.load import dumps
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration

from src.config import CACHE_DIR
from src.ingest.chunk import chunk_corpus
from src.ingest.extract import _format_chunk, _system_prompt
from src.logging_config import configure_logging, get_logger
from src.models.extraction import ExtractionResult

configure_logging()
log = get_logger("repair_cache")

TARGETS = {
    "services/user-service.md#overview",
    "services/user-service.md#security",
    "teams/data-team.md",
}

_ENTITY_REQUIRED = ("id", "type", "canonical_name", "confidence")
_REL_REQUIRED = (
    "source_id", "source_name", "type", "target_id", "target_name",
    "confidence", "evidence",
)


def _first_attempt_prompt(chunk) -> str:
    return dumps(
        [
            SystemMessage(content=_system_prompt()),
            HumanMessage(content=_format_chunk(chunk)),
        ]
    )


def _well_formed(rows: list[dict], required: tuple[str, ...]) -> tuple[list[dict], int]:
    kept = [r for r in rows if all(k in r and r[k] is not None for k in required)]
    return kept, len(rows) - len(kept)


def _clean_payload(text: str) -> tuple[str | None, dict[str, int]]:
    """Return (new_text, dropped) or (None, {}) if nothing needed dropping."""
    payload = json.loads(text)
    entities, e_dropped = _well_formed(payload.get("entities", []), _ENTITY_REQUIRED)
    rels, r_dropped = _well_formed(payload.get("relationships", []), _REL_REQUIRED)
    if not e_dropped and not r_dropped:
        return None, {}
    payload["entities"] = entities
    payload["relationships"] = rels
    # sanity: the trimmed payload must now be a valid ExtractionResult
    ExtractionResult.model_validate(payload)
    return json.dumps(payload), {"entities": e_dropped, "relationships": r_dropped}


def _cached_text(response: str) -> str:
    return json.loads(response)["kwargs"]["text"]


def _repack(new_text: str) -> str:
    return dumps(ChatGeneration(message=AIMessage(content=new_text), text=new_text))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="apply the fix (default: dry run)")
    args = parser.parse_args(argv)

    chunks = {c.chunk_id: c for c in chunk_corpus() if c.chunk_id in TARGETS}
    db = CACHE_DIR / "llm.db"
    conn = sqlite3.connect(db)
    backups: list[str] = []
    changed = 0

    for chunk_id, chunk in chunks.items():
        prompt = _first_attempt_prompt(chunk)
        rows = conn.execute(
            "SELECT llm, idx, response FROM full_llm_cache WHERE prompt = ?", (prompt,)
        ).fetchall()
        if not rows:
            log.warning("%s: no cache row", chunk_id)
            continue
        for llm, idx, response in rows:
            new_text, dropped = _clean_payload(_cached_text(response))
            if new_text is None:
                log.info("%s: nothing malformed", chunk_id)
                continue
            log.info("%s: dropping %s", chunk_id, dropped)
            backups.append(json.dumps({"prompt": prompt, "llm": llm, "idx": idx, "response": response}))
            if args.write:
                conn.execute(
                    "UPDATE full_llm_cache SET response = ? WHERE prompt = ? AND llm = ? AND idx = ?",
                    (_repack(new_text), prompt, llm, idx),
                )
            changed += 1

    if args.write and backups:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_path = CACHE_DIR / f"llm.db.repair-backup.{stamp}.jsonl"
        backup_path.write_text("\n".join(backups) + "\n", encoding="utf-8")
        conn.commit()
        log.info("wrote %d row(s); backup -> %s", changed, backup_path.name)
    conn.close()

    print(f"\n{'repaired' if args.write else 'would repair'} {changed} cache row(s)")
    if not args.write and changed:
        print("re-run with --write to apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
