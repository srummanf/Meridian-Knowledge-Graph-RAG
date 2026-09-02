"""Step 5 — run the benchmark through both systems.

1. Parse ``data/benchmark/questions.md`` into
   ``tests/fixtures/benchmark_questions.json`` (id, question, category, gold
   route, gold answer, gold sources).
2. Run every question through the **graph** system (``pipeline.graph.answer_question``)
   and the **vector-only** baseline (``baselines.vector_only.answer_vector_only``),
   recording answer text, latency, cited chunk ids, route used, notes, and an
   estimated token count.
3. Write the raw run to ``tests/fixtures/benchmark_run.json`` (incrementally, so
   a kill mid-run loses nothing) and a grading skeleton to ``BENCHMARK_RESULTS.md``
   for the manual scoring step.

    python scripts/benchmark.py                 # both systems, all questions
    python scripts/benchmark.py --only graph    # one system
    python scripts/benchmark.py --parse-only    # just refresh the fixture

LLM calls are cached in ``cache/llm.db`` — the first pass is slow on the free
tier, reruns are fast.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable
from typing import NamedTuple

from src.baselines.vector_only import answer_vector_only
from src.config import REPO_ROOT
from src.logging_config import configure_logging, get_logger
from src.pipeline.graph import answer_question
from src.pipeline.merge import labelled_context

configure_logging()
log = get_logger("benchmark")

QUESTIONS_MD = REPO_ROOT / "data" / "benchmark" / "questions.md"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "benchmark_questions.json"
RUN_JSON = REPO_ROOT / "tests" / "fixtures" / "benchmark_run.json"
RESULTS_MD = REPO_ROOT / "docs" / "results" / "BENCHMARK_RESULTS.md"

CATEGORY_LABELS = {
    "1": "1-hop",
    "2": "2-hop",
    "3": "3-hop",
    "4": "aggregation",
    "5": "refusal",
}

_QUESTION_RE = re.compile(
    r"\*\*(B\d+)\.\s+(.+?)\*\*\s*\n(.*?)(?=\n\*\*B\d+\.|\n---|\n## |\Z)", re.DOTALL
)
_CATEGORY_RE = re.compile(r"^##\s+Category\s+(\d+)\b", re.MULTILINE)
_FIELD_RE = re.compile(
    r"Route:\s*(?P<route>\w+).*?"
    r"Gold:\s*(?P<gold>.+?)"
    r"(?:\n\s*Sources:\s*(?P<sources>.+?))?\s*$",
    re.DOTALL,
)


class Question(NamedTuple):
    id: str
    question: str
    category: str  # "1-hop" | "2-hop" | "3-hop" | "aggregation" | "refusal"
    gold_route: str
    gold_answer: str
    gold_sources: list[str]


def _dedent(text: str) -> str:
    return " ".join(line.strip() for line in text.strip().splitlines() if line.strip())


def _category_at(md: str, position: int) -> str:
    current = "1"
    for match in _CATEGORY_RE.finditer(md):
        if match.start() > position:
            break
        current = match.group(1)
    return CATEGORY_LABELS.get(current, current)


def parse_benchmark(md: str) -> list[Question]:
    out: list[Question] = []
    for match in _QUESTION_RE.finditer(md):
        qid, question, body = match.group(1), match.group(2).strip(), match.group(3)
        fields = _FIELD_RE.search(body)
        if fields is None:
            raise ValueError(f"{qid}: could not parse Route/Gold block")
        sources_raw = fields.group("sources") or ""
        sources = [
            s.strip()
            for s in re.split(r"[,\n]| \+ ", _dedent(sources_raw))
            if s.strip() and "/" in s
        ]
        out.append(
            Question(
                id=qid,
                question=question,
                category=_category_at(md, match.start()),
                gold_route=fields.group("route").strip(),
                gold_answer=_dedent(fields.group("gold")),
                gold_sources=sources,
            )
        )
    return out


def write_fixture(questions: list[Question]) -> None:
    FIXTURE.write_text(
        json.dumps([q._asdict() for q in questions], indent=2) + "\n", encoding="utf-8"
    )
    log.info("wrote %d questions -> %s", len(questions), FIXTURE.name)


# --------------------------------------------------------------------------- #
# running
# --------------------------------------------------------------------------- #
def _est_tokens(question: str, context_text: str, answer: str) -> int:
    """chars/4 estimate of prompt + completion (the project's token convention)."""
    return (len(question) + len(context_text) + len(answer)) // 4


def run_one(system: Callable[[str], dict], question: str) -> dict:
    started = time.perf_counter()
    state = system(question)
    elapsed_ms = (time.perf_counter() - started) * 1000

    context = state.get("context")
    context_text = labelled_context(context) if context else ""
    answer = state.get("answer")
    route_used = state.get("route_used", "?")

    if answer is None:  # graph system refused
        return {
            "route_used": route_used,
            "answer": "(refused)",
            "citations": [],
            "notes": state.get("notes", []),
            "latency_ms": round(elapsed_ms, 1),
            "est_tokens": _est_tokens(question, context_text, ""),
        }
    return {
        "route_used": route_used,
        "answer": answer.answer,
        "citations": [c.chunk_id for c in answer.citations],
        "notes": answer.notes,
        "latency_ms": round(elapsed_ms, 1),
        "est_tokens": _est_tokens(question, context_text, answer.answer),
    }


SYSTEMS: dict[str, Callable[[str], dict]] = {
    "graph": answer_question,
    "vector": answer_vector_only,
}


def run_benchmark(questions: list[Question], systems: list[str]) -> dict:
    run: dict = json.loads(RUN_JSON.read_text("utf-8")) if RUN_JSON.exists() else {}
    for q in questions:
        entry = run.setdefault(q.id, {"question": q.question, "category": q.category})
        for name in systems:
            if name in entry:
                continue  # already recorded — resume safely
            log.info("%s / %s: %s", q.id, name, q.question)
            entry[name] = run_one(SYSTEMS[name], q.question)
            RUN_JSON.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    return run


# --------------------------------------------------------------------------- #
# grading skeleton
# --------------------------------------------------------------------------- #
def write_results_md(questions: list[Question], run: dict) -> None:
    # Once the file carries manual scores it is hand-maintained — don't clobber
    # it. The raw run is always recoverable from benchmark_run.json.
    if RESULTS_MD.exists() and re.search(r"\|\s*[01]\.\d+\s*\|", RESULTS_MD.read_text("utf-8")):
        log.info("%s already has scores — leaving it (raw run in %s)", RESULTS_MD.name, RUN_JSON.name)
        return
    by_id = {q.id: q for q in questions}
    lines = [
        "# Benchmark Results — Graph RAG vs. Vector-only",
        "",
        "Raw run: `tests/fixtures/benchmark_run.json`. Rubric: `data/benchmark/",
        "questions.md` (0 / 0.25 / 0.5 / 0.75 / 1.0). Fill `G` (graph) and `V`",
        "(vector) with a manual score, then run `python scripts/score_benchmark.py`.",
        "",
        "| ID | Cat | Question | Gold route | Graph route | G | V | Notes |",
        "|----|-----|----------|-----------|-------------|---|---|-------|",
    ]
    for qid, entry in run.items():
        q = by_id[qid]
        g = entry.get("graph", {})
        lines.append(
            f"| {qid} | {q.category} | {q.question} | {q.gold_route} | "
            f"{g.get('route_used', '-')} |  |  |  |"
        )
    lines += [
        "",
        "## Per-question detail",
        "",
    ]
    for qid, entry in run.items():
        q = by_id[qid]
        lines.append(f"### {qid} ({q.category}) — {q.question}")
        lines.append(f"**Gold:** {q.gold_answer}")
        lines.append(f"**Gold sources:** {', '.join(q.gold_sources) or '—'}")
        for name in ("graph", "vector"):
            r = entry.get(name)
            if not r:
                continue
            lines.append(
                f"\n**{name}** ({r['route_used']}, {r['latency_ms']:.0f} ms, "
                f"~{r['est_tokens']} tok): {r['answer']}"
            )
            lines.append(f"  citations: {r['citations'] or '—'}")
            if r["notes"]:
                lines.append(f"  notes: {r['notes']}")
        lines.append("")
    RESULTS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("wrote %s", RESULTS_MD.name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=list(SYSTEMS), help="run just one system")
    parser.add_argument("--parse-only", action="store_true", help="refresh the fixture and stop")
    parser.add_argument(
        "--questions",
        help="comma-separated ids to run (e.g. B17,B24) — free-tier friendly subset",
    )
    args = parser.parse_args(argv)

    all_questions = parse_benchmark(QUESTIONS_MD.read_text("utf-8"))
    write_fixture(all_questions)
    log.info("parsed %d benchmark questions", len(all_questions))
    if args.parse_only:
        return 0

    to_run = all_questions
    if args.questions:
        wanted = {q.strip().upper() for q in args.questions.split(",")}
        to_run = [q for q in all_questions if q.id in wanted]
        log.info("subset: %s", [q.id for q in to_run])

    systems = [args.only] if args.only else list(SYSTEMS)
    run = run_benchmark(to_run, systems)
    write_results_md(all_questions, run)  # skeleton covers every id that has a run entry

    print(f"\nran {len(run)} questions x {len(systems)} system(s)")
    print(f"raw -> {RUN_JSON.name}   grading skeleton -> {RESULTS_MD.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
