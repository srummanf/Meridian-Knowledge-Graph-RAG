"""Phase 4.2 — citation validity across the sample, and the bad-citation catch.

Two checks:

1. **100% validity** — every question in ``tests/fixtures/synthesis_eval.json``
   run through the *full* pipeline (``answer_question``: retrieve → merge →
   synthesize → validate) must come back with every ``citation.chunk_id`` in the
   retrieved set.
2. **injected bad citation is caught** — a fabricated citation spliced into a
   real synthesised answer is removed by ``validate_answer`` (one regeneration).

    python scripts/eval_validation.py

Synthesis / plan / route calls are cached in ``cache/llm.db``.
"""

from __future__ import annotations

import sys
from typing import NamedTuple

from scripts.eval_synthesis import load_eval_set
from src.logging_config import configure_logging, get_logger
from src.models.answer import Citation
from src.pipeline.graph import answer_question
from src.pipeline.synthesize import synthesize
from src.pipeline.validate import validate_answer

configure_logging()
log = get_logger("eval_validation")


class Case(NamedTuple):
    question: str
    ok: bool
    detail: str


def _validity_cases() -> list[Case]:
    cases: list[Case] = []
    for item in load_eval_set():
        state = answer_question(item["question"])
        answer = state.get("answer")
        if answer is None:
            cases.append(Case(item["question"], False, "no answer (refused?)"))
            continue
        retrieved = set(state["context"].chunk_ids)
        bad = [c.chunk_id for c in answer.citations if c.chunk_id not in retrieved]
        cases.append(
            Case(item["question"], not bad, f"invalid: {bad}" if bad else f"{len(answer.citations)} ok")
        )
    return cases


def _injection_case() -> Case:
    question = "Which services use PostgreSQL?"
    state = answer_question(question)
    context = state["context"]
    base = synthesize(question, context, routing_used="GRAPH")

    poisoned = base.model_copy(
        update={
            "citations": [
                *base.citations,
                Citation(claim="fabricated", chunk_id="does/not/exist.md", source_type="GRAPH"),
            ]
        }
    )
    fixed = validate_answer(poisoned, context, question=question)
    retrieved = set(context.chunk_ids)
    leaked = [c.chunk_id for c in fixed.citations if c.chunk_id not in retrieved]
    ok = not leaked and len(fixed.citations) >= 1
    return Case("injected bad citation", ok, f"leaked {leaked}" if leaked else "removed, note added")


def main(argv: list[str] | None = None) -> int:
    cases = [*_validity_cases(), _injection_case()]

    print("\n=== citation validation eval ===")
    for case in cases:
        print(f"  [{'ok  ' if case.ok else 'FAIL'}]  {case.question}")
        print(f"         {case.detail}")

    passed = sum(c.ok for c in cases)
    print(f"\n{passed}/{len(cases)} valid")
    ok = passed == len(cases)
    print(f"\nPhase 4.2 gate: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
