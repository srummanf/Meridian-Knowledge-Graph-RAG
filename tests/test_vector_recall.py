"""Phase 2.2 gate: vector retrieval finds the right chunk.

Unit test guards the fixture against drift (every gold id must be a real chunk).
The ``pgvector`` test is the gate: recall@5 over the fixture must clear 0.9.
"""

from __future__ import annotations

import pytest

from scripts.eval_vector import build_eval_store, load_eval_set, recall_report
from src.ingest.chunk import chunk_corpus


def test_fixture_gold_ids_are_real_chunks() -> None:
    eval_set = load_eval_set()
    real = {chunk.chunk_id for chunk in chunk_corpus()}
    unknown = [
        pair["gold_chunk_id"]
        for pair in eval_set.pairs
        if pair["gold_chunk_id"] not in real
    ]
    assert not unknown, f"fixture references chunks that don't exist: {unknown}"
    assert len(eval_set.pairs) >= 10


@pytest.mark.pgvector
def test_recall_at_5_clears_the_gate() -> None:
    eval_set = load_eval_set()
    store = build_eval_store()
    try:
        report = recall_report(store, eval_set.pairs, eval_set.k)
    finally:
        store.delete_collection()

    misses = [q for q, rank in report.ranks if rank == 0]
    assert report.at_5 >= eval_set.gate, (
        f"recall@5 {report.at_5:.2f} < {eval_set.gate}; missed: {misses}"
    )
