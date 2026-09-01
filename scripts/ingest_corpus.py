"""End-to-end ingestion: corpus -> chunks -> extract -> resolve -> Neo4j.

    python scripts/ingest_corpus.py           # MERGE (idempotent; safe to re-run)
    python scripts/ingest_corpus.py --wipe    # clear Neo4j first, then rebuild

Extraction is cached (``cache/llm.db``), so re-runs are fast and free. Phase 2
extends this script to also populate pgvector.
"""

from __future__ import annotations

import argparse
import sys
import time

from src.config import settings
from src.graph.client import graph_client
from src.graph.queries import (
    ENTITY_TYPE_BREAKDOWN,
    RELATIONSHIP_TYPE_BREAKDOWN,
)
from src.ingest.chunk import chunk_corpus
from src.ingest.extract import extract_corpus
from src.ingest.load_graph import load_graph
from src.ingest.resolve import resolve
from src.logging_config import configure_logging, get_logger
from src.utils.errors import LLMUnavailableError

configure_logging(settings.log_level)
log = get_logger("ingest")

ENTITY_TARGET = range(45, 66)          # ONTOLOGY §6
RELATIONSHIP_TARGET = range(140, 201)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wipe", action="store_true", help="clear Neo4j before loading")
    args = parser.parse_args(argv)

    started = time.perf_counter()

    chunks = chunk_corpus()
    log.info("chunked corpus: %d chunks", len(chunks))

    try:
        results, failed = extract_corpus(chunks)
    except LLMUnavailableError as exc:
        print(f"\n=== ingest paused ===\n{exc}\n")
        print("The LLM cache kept every chunk done so far. Re-run this script when "
              "the provider quota resets (Groq free tier: 200K tokens/day).")
        return 2
    if failed:
        log.warning("%d chunk(s) failed extraction: %s", len(failed), [f.chunk_id for f in failed])

    entities, relationships = resolve(results)
    log.info("resolved: %d entities, %d relationships", len(entities), len(relationships))

    counts = load_graph(entities, relationships, wipe_first=args.wipe)

    client = graph_client()
    elapsed = time.perf_counter() - started

    print("\n=== ingest summary ===")
    print(f"chunks: {len(chunks)}   extracted ok: {len(results)}   failed: {len(failed)}")
    print(f"entities: {counts['entities']}   relationships: {counts['relationships']}")
    print(f"edges missing evidence/source: {counts['relationships_missing_evidence']}")
    print(f"edges skipped (bad endpoint): {counts['skipped']}")
    print(f"elapsed: {elapsed / 60:.1f} min\n")

    print("entities by type:")
    for row in client.query(ENTITY_TYPE_BREAKDOWN):
        print(f"  {row['type']:<18} {row['n']}")
    print("relationships by type:")
    for row in client.query(RELATIONSHIP_TYPE_BREAKDOWN):
        print(f"  {row['type']:<18} {row['n']}")

    ok = (
        counts["entities"] in ENTITY_TARGET
        and counts["relationships"] in RELATIONSHIP_TARGET
        and counts["relationships_missing_evidence"] == 0
        and not failed
    )
    print(f"\nPhase 1.4 gate: {'PASS' if ok else 'CHECK'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
