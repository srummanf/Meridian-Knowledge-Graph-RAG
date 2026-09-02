"""Step 5 — score the manually-graded benchmark.

Reads the ``| ID | Cat | Question | Gold route | Graph route | G | V | Notes |``
table in ``BENCHMARK_RESULTS.md`` (fill the ``G`` / ``V`` columns with a rubric
score each: 0, 0.25, 0.5, 0.75, 1.0), then reports mean accuracy per category
for each system and checks the benchmark gate:

- 1-hop:        |graph - vector| <= 0.05        (parity)
- 2-hop:        graph - vector   >= 0.15
- 3-hop:        graph - vector   >= 0.30
- aggregation:  graph >= 0.80  and  vector <= 0.20
- refusal:      reported, not gated

    python scripts/score_benchmark.py

Rows with a blank G or V are listed as "ungraded" and excluded from the means.
"""

from __future__ import annotations

import re
import sys
from typing import NamedTuple

from src.config import REPO_ROOT
from src.logging_config import configure_logging, get_logger

configure_logging()
log = get_logger("score_benchmark")

RESULTS_MD = REPO_ROOT / "docs" / "results" / "BENCHMARK_RESULTS.md"

_ROW_RE = re.compile(
    r"^\|\s*(B\d+)\s*\|\s*([\w-]+)\s*\|.*?\|.*?\|.*?\|\s*([\d.]*)\s*\|\s*([\d.]*)\s*\|",
    re.MULTILINE,
)

GATES = {
    "1-hop": ("parity", 0.05),
    "2-hop": ("graph_ahead", 0.15),
    "3-hop": ("graph_ahead", 0.30),
    "aggregation": ("graph_dominates", (0.80, 0.20)),
}


class Row(NamedTuple):
    id: str
    category: str
    graph: float | None
    vector: float | None


def parse_scores(md: str) -> list[Row]:
    rows: list[Row] = []
    for qid, cat, g, v in _ROW_RE.findall(md):
        rows.append(
            Row(qid, cat, float(g) if g else None, float(v) if v else None)
        )
    return rows


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarise(rows: list[Row]) -> dict[str, dict]:
    cats: dict[str, dict] = {}
    for row in rows:
        c = cats.setdefault(row.category, {"graph": [], "vector": [], "ungraded": []})
        if row.graph is None or row.vector is None:
            c["ungraded"].append(row.id)
        else:
            c["graph"].append(row.graph)
            c["vector"].append(row.vector)
    for c in cats.values():
        c["graph_mean"] = _mean(c["graph"])
        c["vector_mean"] = _mean(c["vector"])
        c["delta"] = c["graph_mean"] - c["vector_mean"]
    return cats


def check_gate(category: str, stats: dict) -> tuple[bool, str]:
    if category not in GATES:
        return True, "not gated"
    kind, threshold = GATES[category]
    g, v, d = stats["graph_mean"], stats["vector_mean"], stats["delta"]
    if kind == "parity":
        return abs(d) <= threshold, f"|delta|={abs(d):.2f} <= {threshold}"
    if kind == "graph_ahead":
        return d >= threshold, f"delta={d:+.2f} >= {threshold}"
    lo, hi = threshold
    return (g >= lo and v <= hi), f"graph={g:.2f}>={lo}, vector={v:.2f}<={hi}"


def main(argv: list[str] | None = None) -> int:
    if not RESULTS_MD.exists():
        log.error("%s not found — run scripts/benchmark.py first", RESULTS_MD.name)
        return 2
    rows = parse_scores(RESULTS_MD.read_text("utf-8"))
    if not rows:
        log.error("no scored rows found in %s", RESULTS_MD.name)
        return 2
    cats = summarise(rows)

    order = ["1-hop", "2-hop", "3-hop", "aggregation", "refusal"]
    print("\n=== benchmark scores ===")
    print(f"{'category':<12} {'graph':>7} {'vector':>7} {'delta':>7}  gate")
    all_pass = True
    for category in order:
        if category not in cats:
            continue
        s = cats[category]
        ok, detail = check_gate(category, s)
        all_pass = all_pass and (ok or category not in GATES)
        mark = "  ok " if ok else " FAIL"
        ungraded = f"  ({len(s['ungraded'])} ungraded)" if s["ungraded"] else ""
        print(
            f"{category:<12} {s['graph_mean']:>7.2f} {s['vector_mean']:>7.2f} "
            f"{s['delta']:>+7.2f} [{mark}] {detail}{ungraded}"
        )

    graded = [r for r in rows if r.graph is not None and r.vector is not None]
    print(f"\n{len(graded)}/{len(rows)} rows graded")
    print(f"\nBenchmark gate: {'PASS' if all_pass and len(graded) == len(rows) else 'INCOMPLETE / FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
