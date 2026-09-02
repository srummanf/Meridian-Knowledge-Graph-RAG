"""Phase 3.1 — router accuracy on the labelled set.

Runs every question in ``tests/fixtures/routing_eval.json`` through
``route_question`` and reports accuracy + a gold x predicted confusion matrix.
Writes ``ROUTING_METRICS.md``. Gate: accuracy >= 0.90.

    python scripts/eval_router.py

Router calls are cached in ``cache/llm.db`` — the first run costs a handful of
small ``gpt-oss-20b`` calls, later runs are free.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import NamedTuple

from src.config import REPO_ROOT
from src.logging_config import configure_logging, get_logger
from src.models.routing import Route
from src.pipeline.router import route_question

configure_logging()
log = get_logger("eval_router")

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "routing_eval.json"
METRICS_MD = REPO_ROOT / "ROUTING_METRICS.md"
ROUTES: tuple[Route, ...] = ("VECTOR", "GRAPH", "HYBRID", "REFUSE")


class Row(NamedTuple):
    question: str
    gold: str
    predicted: str
    confidence: float

    @property
    def correct(self) -> bool:
        return self.gold == self.predicted


class EvalResult(NamedTuple):
    rows: list[Row]

    @property
    def accuracy(self) -> float:
        return sum(r.correct for r in self.rows) / len(self.rows) if self.rows else 0.0

    @property
    def confusion(self) -> dict[str, dict[str, int]]:
        matrix = {g: dict.fromkeys(ROUTES, 0) for g in ROUTES}
        for row in self.rows:
            matrix[row.gold][row.predicted] += 1
        return matrix


def load_eval_set(path: Path = FIXTURE) -> tuple[list[dict], float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["questions"], data.get("accuracy_gate", 0.90)


def run_eval(questions: list[dict], *, model=None) -> EvalResult:
    rows: list[Row] = []
    for item in questions:
        decision = route_question(item["question"], model=model)
        rows.append(
            Row(
                item["question"],
                item["gold_route"],
                decision.route,
                decision.confidence,
            )
        )
    return EvalResult(rows)


def render_metrics_md(result: EvalResult, gate: float) -> str:
    lines = [
        "# Routing Metrics",
        "",
        f"Router: `gpt-oss-20b` via `src/pipeline/router.py`. "
        f"Eval set: `tests/fixtures/routing_eval.json` ({len(result.rows)} questions).",
        "",
        f"**Accuracy: {result.accuracy:.1%}** (gate ≥ {gate:.0%}) — "
        f"{'PASS' if result.accuracy >= gate else 'FAIL'}",
        "",
        "## Confusion matrix (gold → predicted)",
        "",
        "| gold ↓ / pred → | " + " | ".join(ROUTES) + " |",
        "|" + "---|" * (len(ROUTES) + 1),
    ]
    matrix = result.confusion
    for gold in ROUTES:
        cells = " | ".join(str(matrix[gold][p]) for p in ROUTES)
        lines.append(f"| **{gold}** | {cells} |")

    misses = [r for r in result.rows if not r.correct]
    if misses:
        lines += ["", "## Misclassifications", ""]
        for row in misses:
            lines.append(
                f"- `{row.gold}` → `{row.predicted}` (conf {row.confidence:.2f}): "
                f"{row.question}"
            )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    questions, gate = load_eval_set()
    result = run_eval(questions)

    print("\n=== router eval ===")
    for row in result.rows:
        mark = "ok  " if row.correct else "MISS"
        print(f"  [{mark}] {row.gold:>6} -> {row.predicted:<6} {row.question}")
    print(f"\naccuracy = {result.accuracy:.1%}  (n={len(result.rows)}, gate {gate:.0%})")

    METRICS_MD.write_text(render_metrics_md(result, gate), encoding="utf-8")
    print(f"wrote {METRICS_MD.relative_to(REPO_ROOT)}")

    ok = result.accuracy >= gate
    print(f"\nPhase 3.1 gate: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
