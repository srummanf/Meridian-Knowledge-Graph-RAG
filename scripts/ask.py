"""Ask the pipeline a question from the command line.

    python scripts/ask.py "Which services use PostgreSQL?"
    python scripts/ask.py "Which services use PostgreSQL?" --json

Runs the full LangGraph pipeline (route -> retrieve -> merge -> synthesize ->
validate) and prints the grounded answer. Needs the datastores up and the corpus
loaded (``python scripts/ingest_corpus.py --wipe``). LLM calls are cached in
``cache/llm.db``.
"""

from __future__ import annotations

import argparse
import json
import sys

from src.logging_config import configure_logging
from src.pipeline.graph import answer_question

_REFUSAL = (
    "Out of scope. This system answers questions about Meridian's architecture "
    "and ownership, not opinions, forecasts, or costs."
)


def _print_human(state: dict) -> None:
    route = state.get("route_used", "?")
    print(f"\nroute:   {route}")

    if route == "REFUSE" or state.get("answer") is None:
        decision = state.get("decision")
        print(f"answer:  {_REFUSAL}")
        if decision is not None:
            print(f"reason:  {decision.reasoning}")
        return

    answer = state["answer"]
    print(f"latency: {answer.latency_ms:.0f} ms\n")
    print(answer.answer)
    if answer.citations:
        print("\nsources:")
        for citation in answer.citations:
            print(f"  - [{citation.source_type}] {citation.chunk_id}")
    for note in answer.notes:
        print(f"\nnote: {note}")


def _to_dict(state: dict) -> dict:
    answer = state.get("answer")
    if answer is None:
        return {"question": state["question"], "route_used": "REFUSE", "answer": _REFUSAL}
    return answer.model_dump()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="the question to ask")
    parser.add_argument("--json", action="store_true", help="print the raw GroundedAnswer as JSON")
    args = parser.parse_args(argv)

    configure_logging("WARNING")  # keep pipeline info logs out of the output
    state = answer_question(args.question)

    if args.json:
        print(json.dumps(_to_dict(state), indent=2))
    else:
        _print_human(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
