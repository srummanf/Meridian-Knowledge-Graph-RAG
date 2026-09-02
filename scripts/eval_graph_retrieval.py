"""Phase 3.2 — graph retriever on the benchmark's GRAPH questions.

Runs each question in ``tests/fixtures/graph_eval.json`` through
``retrieve_graph`` (real plan LLM + live Neo4j) and checks that every gold node
comes back, that ``exact`` questions match exactly, and that the ≤3-hop queries
stay under the latency budget.

    python scripts/eval_graph_retrieval.py

The plan calls are cached in ``cache/llm.db``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import NamedTuple

from src.config import REPO_ROOT
from src.graph.client import graph_client
from src.logging_config import configure_logging, get_logger
from src.pipeline.retrieve_graph import retrieve_graph

configure_logging()
log = get_logger("eval_graph")

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "graph_eval.json"


class Case(NamedTuple):
    question: str
    ok: bool
    detail: str
    ms: float


def load_eval_set(path: Path = FIXTURE) -> tuple[list[dict], int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["questions"], data.get("max_query_ms", 200)


def check(item: dict, *, model=None, client=None) -> Case:
    result = retrieve_graph(item["question"], model=model, client=client)
    ms = result.query_ms  # Cypher only — the plan LLM call is not part of the gate

    got = set(result.node_names)
    gold = set(item["gold_nodes"])
    allowed = gold | set(item.get("extra_ok", []))

    problems: list[str] = []
    missing = gold - got
    if missing:
        problems.append(f"missing {sorted(missing)}")
    if item.get("exact") and got != gold:
        problems.append(f"not exact (+{sorted(got - gold)})")
    extra = got - allowed
    if extra and not item.get("exact"):
        problems.append(f"unexpected {sorted(extra)}")
    if "expected_count" in item:
        lead = result.facts[0].text if result.facts else ""
        if not lead.startswith(f"{item['expected_count']} "):
            problems.append(f"count sentence wrong: {lead!r}")

    detail = "; ".join(problems) if problems else f"{sorted(got)}"
    return Case(item["question"], not problems, detail, ms)


def main(argv: list[str] | None = None) -> int:
    questions, budget = load_eval_set()
    client = graph_client()
    cases = [check(item, client=client) for item in questions]

    print("\n=== graph retrieval eval ===")
    for case in cases:
        mark = "ok  " if case.ok else "FAIL"
        slow = "  SLOW" if case.ms > budget else ""
        print(f"  [{mark}] {case.ms:6.1f}ms{slow}  {case.question}")
        print(f"         {case.detail}")

    passed = sum(c.ok for c in cases)
    within_budget = all(c.ms <= budget for c in cases)
    print(f"\n{passed}/{len(cases)} correct; all < {budget}ms: {within_budget}")
    ok = passed == len(cases) and within_budget
    print(f"\nPhase 3.2 gate: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
