"""Phase 3.3 — vector retriever on the benchmark's VECTOR questions.

Runs each question in ``tests/fixtures/vector_retrieval_eval.json`` through
``retrieve_vector`` against the live ``meridian_chunks`` collection and checks
that an acceptable source chunk lands in the top ``rank_within`` results.

    python scripts/eval_vector_retrieval.py

No LLM call and no cache — embeddings are local (``bge-small``). Needs Postgres
up with the corpus loaded (``scripts/ingest_corpus.py``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import NamedTuple

from src.config import REPO_ROOT
from src.logging_config import configure_logging, get_logger
from src.pipeline.retrieve_vector import retrieve_vector

configure_logging()
log = get_logger("eval_vector_retrieval")

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "vector_retrieval_eval.json"


class Case(NamedTuple):
    question: str
    ok: bool
    rank: int  # 1-based rank of the first gold chunk; 0 = not in top-k
    detail: str


def load_eval_set(path: Path = FIXTURE) -> tuple[list[dict], int, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["questions"], data.get("rank_within", 3), data.get("k", 5)


def check(item: dict, *, rank_within: int, k: int, store=None) -> Case:
    passages = retrieve_vector(item["question"], k=k, store=store)
    found = [p.chunk_id for p in passages]
    gold = set(item["gold_chunks"])

    ranks = [i + 1 for i, cid in enumerate(found) if cid in gold]
    best = min(ranks) if ranks else 0
    ok = best != 0 and best <= rank_within
    detail = f"top-{k}: {found}" if ok else f"gold {sorted(gold)} not in top-{rank_within}; got {found}"
    return Case(item["question"], ok, best, detail)


def main(argv: list[str] | None = None) -> int:
    questions, rank_within, k = load_eval_set()
    cases = [check(item, rank_within=rank_within, k=k) for item in questions]

    print("\n=== vector retrieval eval ===")
    for case in cases:
        mark = "ok  " if case.ok else "FAIL"
        rank = f"rank {case.rank}" if case.rank else "MISS"
        print(f"  [{mark}] {rank:>6}  {case.question}")
        if not case.ok:
            print(f"         {case.detail}")

    passed = sum(c.ok for c in cases)
    print(f"\n{passed}/{len(cases)} within top-{rank_within}")
    ok = passed == len(cases)
    print(f"\nPhase 3.3 gate: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
