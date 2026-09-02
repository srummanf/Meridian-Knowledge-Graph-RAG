"""Phase 4.1 — synthesis quality on a 5-question sample.

Runs each question in ``tests/fixtures/synthesis_eval.json`` through the full
pipeline (``run_pipeline``) then ``synthesize`` and checks that the answer is
coherent and fully cited:

- non-empty, and not the "context does not answer this" sentinel;
- at least one citation;
- every ``citation.chunk_id`` is non-empty and in the retrieved set;
- every ``must_mention`` string appears in the answer (case-insensitive).

    python scripts/eval_synthesis.py

The synthesis + plan + route LLM calls are cached in ``cache/llm.db``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import NamedTuple

from src.config import REPO_ROOT
from src.logging_config import configure_logging, get_logger
from src.pipeline.graph import run_pipeline
from src.pipeline.synthesize import synthesize

configure_logging()
log = get_logger("eval_synthesis")

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "synthesis_eval.json"
NO_ANSWER_PREFIX = "The retrieved context does not contain"


class Case(NamedTuple):
    question: str
    ok: bool
    detail: str
    answer: str


def load_eval_set(path: Path = FIXTURE) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["questions"]


def check(item: dict) -> Case:
    state = run_pipeline(item["question"])
    context = state["context"]
    answer = synthesize(
        item["question"], context, routing_used=_routing_used(state["route_used"])
    )

    problems: list[str] = []
    if not answer.answer.strip() or answer.answer.startswith(NO_ANSWER_PREFIX):
        problems.append("no answer produced")
    if not answer.citations:
        problems.append("no citations")

    retrieved = set(context.chunk_ids)
    for citation in answer.citations:
        if not citation.chunk_id:
            problems.append("citation with empty chunk_id")
        elif citation.chunk_id not in retrieved:
            problems.append(f"citation {citation.chunk_id!r} not in retrieved set")

    lowered = answer.answer.lower()
    missing = [m for m in item.get("must_mention", []) if m.lower() not in lowered]
    if missing:
        problems.append(f"answer missing {missing}")

    detail = "; ".join(problems) if problems else f"{len(answer.citations)} citations"
    return Case(item["question"], not problems, detail, answer.answer)


def _routing_used(route: str) -> str:
    return "HYBRID" if route not in ("VECTOR", "GRAPH", "HYBRID") else route


def main(argv: list[str] | None = None) -> int:
    cases = [check(item) for item in load_eval_set()]

    print("\n=== synthesis eval ===")
    for case in cases:
        mark = "ok  " if case.ok else "FAIL"
        print(f"\n  [{mark}] {case.question}")
        print(f"         {case.detail}")
        preview = case.answer.strip()[:300].encode("ascii", "replace").decode("ascii")
        print(f"         > {preview}")

    passed = sum(c.ok for c in cases)
    print(f"\n{passed}/{len(cases)} coherent + fully cited")
    ok = passed == len(cases)
    print(f"\nPhase 4.1 gate: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
