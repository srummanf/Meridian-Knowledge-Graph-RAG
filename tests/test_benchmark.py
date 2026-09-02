"""Phase 5: benchmark parser + scorer (offline, no pipeline)."""

from __future__ import annotations

from scripts.benchmark import parse_benchmark
from scripts.score_benchmark import check_gate, parse_scores, summarise
from src.config import REPO_ROOT

_MD = (REPO_ROOT / "data" / "benchmark" / "questions.md").read_text("utf-8")


# --------------------------------------------------------------------------- #
# parse_benchmark
# --------------------------------------------------------------------------- #
EXPECTED_IDS = [
    "B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08",
    "B09", "B10", "B17", "B18", "B24", "B28",
]


def test_parses_the_scoped_question_set() -> None:
    questions = parse_benchmark(_MD)
    assert [q.id for q in questions] == EXPECTED_IDS


def test_categories_map_to_labels() -> None:
    by_id = {q.id: q for q in parse_benchmark(_MD)}
    assert by_id["B01"].category == "1-hop"
    assert by_id["B09"].category == "2-hop"
    assert by_id["B17"].category == "3-hop"
    assert by_id["B18"].category == "3-hop"
    assert by_id["B24"].category == "aggregation"
    assert by_id["B28"].category == "refusal"


def test_routes_and_sources_extracted() -> None:
    by_id = {q.id: q for q in parse_benchmark(_MD)}
    assert by_id["B01"].gold_route == "VECTOR"
    assert by_id["B09"].gold_route == "GRAPH"
    assert by_id["B28"].gold_route == "REFUSE"
    assert "services/auth-service.md#overview" in by_id["B01"].gold_sources
    assert by_id["B28"].gold_sources == []  # REFUSE questions list no sources


def test_gold_answer_is_flattened_to_one_line() -> None:
    b28 = {q.id: q for q in parse_benchmark(_MD)}["B28"]
    assert "\n" not in b28.gold_answer
    assert b28.gold_answer.startswith("Opinion")


# --------------------------------------------------------------------------- #
# score_benchmark
# --------------------------------------------------------------------------- #
_SCORED = """
| ID | Cat | Question | Gold route | Graph route | G | V | Notes |
|----|-----|----------|-----------|-------------|---|---|-------|
| B01 | 1-hop | q | VECTOR | VECTOR | 1.0 | 1.0 |  |
| B02 | 1-hop | q | VECTOR | VECTOR | 0.75 | 0.75 |  |
| B09 | 2-hop | q | GRAPH | GRAPH | 1.0 | 0.5 |  |
| B24 | aggregation | q | GRAPH | GRAPH | 1.0 | 0.0 |  |
| B25 | aggregation | q | GRAPH | GRAPH | 0.75 |  |  |
"""


def test_parse_scores_reads_g_and_v_columns() -> None:
    rows = {r.id: r for r in parse_scores(_SCORED)}
    assert rows["B01"].graph == 1.0 and rows["B01"].vector == 1.0
    assert rows["B25"].graph == 0.75
    assert rows["B25"].vector is None  # blank cell


def test_summarise_means_and_ungraded() -> None:
    cats = summarise(parse_scores(_SCORED))
    assert cats["1-hop"]["graph_mean"] == 0.875
    assert cats["2-hop"]["delta"] == 0.5
    assert cats["aggregation"]["ungraded"] == ["B25"]


def test_gate_checks() -> None:
    cats = summarise(parse_scores(_SCORED))
    assert check_gate("1-hop", cats["1-hop"])[0] is True  # parity
    assert check_gate("2-hop", cats["2-hop"])[0] is True  # +0.50 >= 0.15
    # aggregation: graph 1.0 >= 0.8, vector 0.0 <= 0.2 (B25 excluded as ungraded)
    assert check_gate("aggregation", cats["aggregation"])[0] is True
