"""Phase 2.2 — vector-retrieval recall sanity check.

Builds the corpus into a scratch collection (chunks only — no LLM, no graph),
runs each fixture question through similarity search, and reports recall@1/3/5.
Gate: recall@5 >= 0.9 (expect ~1.0).

    python scripts/eval_vector.py

**Why there is no ANN index.** The corpus is ~42 vectors. pgvector's exact scan
over 42 rows is sub-millisecond, and being exact its recall is 1.0 by
construction. HNSW / IVFFlat trade exactness for speed on datasets 3–5 orders of
magnitude larger; at this size an approximate index would only add build time
and a chance of *missing* the right chunk. So `load_vector` creates none, and
this check confirms retrieval quality is a non-issue for the vector half.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import NamedTuple

from src.config import REPO_ROOT
from src.ingest.chunk import chunk_corpus
from src.ingest.load_vector import load_vector, vector_store
from src.logging_config import configure_logging, get_logger

configure_logging()
log = get_logger("eval_vector")

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "vector_eval.json"
EVAL_COLLECTION = "meridian_eval"


class EvalSet(NamedTuple):
    pairs: list[dict]
    gate: float
    k: int


class RecallReport(NamedTuple):
    at_1: float
    at_3: float
    at_5: float
    ranks: list[tuple[str, int]]  # (question, rank; 0 = miss)


def load_eval_set(path: Path = FIXTURE) -> EvalSet:
    data = json.loads(path.read_text(encoding="utf-8"))
    return EvalSet(data["pairs"], data.get("recall_at_5_gate", 0.9), data.get("k", 5))


def build_eval_store():
    """Populate the scratch collection from every chunk (idempotent, ~15s, $0)."""
    store = vector_store(collection=EVAL_COLLECTION)
    load_vector(chunk_corpus(), [], store=store, wipe_first=True)
    return store


def recall_report(store, pairs: list[dict], k: int = 5) -> RecallReport:
    hits = {1: 0, 3: 0, 5: 0}
    ranks: list[tuple[str, int]] = []
    for pair in pairs:
        found = [
            doc.metadata["chunk_id"]
            for doc in store.similarity_search(pair["question"], k=k)
        ]
        gold = pair["gold_chunk_id"]
        rank = found.index(gold) + 1 if gold in found else 0
        ranks.append((pair["question"], rank))
        for threshold in hits:
            if 0 < rank <= threshold:
                hits[threshold] += 1
    n = len(pairs)
    return RecallReport(hits[1] / n, hits[3] / n, hits[5] / n, ranks)


def main(argv: list[str] | None = None) -> int:
    eval_set = load_eval_set()
    store = build_eval_store()
    try:
        report = recall_report(store, eval_set.pairs, eval_set.k)
    finally:
        store.delete_collection()

    print("\n=== vector recall ===")
    for question, rank in report.ranks:
        marker = f"rank {rank}" if rank else "MISS"
        print(f"  [{marker:>7}]  {question}")
    print(
        f"\nrecall@1 = {report.at_1:.2f}   "
        f"recall@3 = {report.at_3:.2f}   "
        f"recall@5 = {report.at_5:.2f}   "
        f"(n={len(eval_set.pairs)})"
    )
    ok = report.at_5 >= eval_set.gate
    print(f"\nPhase 2.2 gate: {'PASS' if ok else 'FAIL'} (recall@5 >= {eval_set.gate})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
