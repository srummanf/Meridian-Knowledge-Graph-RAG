"""End-to-end ingestion: corpus -> chunks -> extract -> resolve -> Neo4j + pgvector.

    python scripts/ingest_corpus.py           # upsert (idempotent; safe to re-run)
    python scripts/ingest_corpus.py --wipe    # clear both stores first, then rebuild

Extraction is cached (``cache/llm.db``), so re-runs are fast and free. Embeddings
are local (``bge-small``), so the vector load never touches an API.
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
from src.ingest.load_vector import load_vector
from src.ingest.resolve import resolve
from src.logging_config import configure_logging, get_logger
from src.utils.errors import LLMUnavailableError

configure_logging(settings.log_level)
log = get_logger("ingest")

ENTITY_TARGET = range(45, 66)          # ONTOLOGY §6
RELATIONSHIP_TARGET = range(140, 201)

# Chunks parked for a later top-up run. Previously held three oversized
# user-service / data-team chunks; their cached extractions were recovered and
# folded back in (2026-09-02), so the set is now empty. Add a chunk id here to
# skip it without aborting a run.
DEFERRED_CHUNKS: set[str] = set()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="clear Neo4j + the pgvector collection before loading",
    )
    args = parser.parse_args(argv)

    started = time.perf_counter()

    chunks = chunk_corpus()
    log.info("chunked corpus: %d chunks", len(chunks))

    try:
        results, failed = extract_corpus(chunks, skip=DEFERRED_CHUNKS)
    except LLMUnavailableError as exc:
        print(f"\n=== ingest paused ===\n{exc}\n")
        print("The LLM cache kept every chunk done so far. Re-run this script when "
              "the provider quota resets (Groq free tier: 200K tokens/day).")
        return 2
    deferred = [f for f in failed if f.errors == ["deferred: in skip set"]]
    real_failures = [f for f in failed if f not in deferred]
    if real_failures:
        log.warning(
            "%d chunk(s) failed extraction: %s",
            len(real_failures),
            [f.chunk_id for f in real_failures],
        )

    entities, relationships = resolve(results)
    log.info("resolved: %d entities, %d relationships", len(entities), len(relationships))

    counts = load_graph(entities, relationships, wipe_first=args.wipe)

    vcounts = load_vector(chunks, results, wipe_first=args.wipe)
    log.info("embedded %d chunks into pgvector", vcounts["chunks_embedded"])

    client = graph_client()
    elapsed = time.perf_counter() - started

    print("\n=== ingest summary ===")
    print(
        f"chunks: {len(chunks)}   extracted ok: {len(results)}   "
        f"deferred: {len(deferred)}   failed: {len(real_failures)}"
    )
    if deferred:
        print(f"deferred chunks (top up later): {[f.chunk_id for f in deferred]}")
    print(f"entities: {counts['entities']}   relationships: {counts['relationships']}")
    print(f"edges missing evidence/source: {counts['relationships_missing_evidence']}")
    print(f"edges skipped (bad endpoint): {counts['skipped']}")
    print(
        f"vectors: {vcounts['chunks_embedded']} chunks embedded "
        f"({vcounts['dim']}-dim, local)"
    )
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
        and not real_failures
        and not deferred
    )
    if deferred and not real_failures:
        print(
            f"\nIngestion gate: PROVISIONAL "
            f"({len(results)}/{len(chunks)} chunks; {len(deferred)} deferred)"
        )
        return 1
    print(f"\nIngestion gate: {'PASS' if ok else 'CHECK'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
