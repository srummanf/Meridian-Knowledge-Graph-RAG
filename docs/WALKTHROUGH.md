# Walkthrough

Every script and test, phase by phase, with the output to expect. Assumes the
setup in [`../SETUP.md`](../SETUP.md) is done: containers up, `.venv` active,
`pip install -e ".[dev]"`, `.env` filled.

Run scripts with the repo root on the path:

```bash
export PYTHONPATH=.          # Windows PowerShell: $env:PYTHONPATH="."
```

Markers used below:

| Marker | Needs |
|--------|-------|
| _(none)_ | nothing external |
| `-m neo4j` | Neo4j running + corpus loaded |
| `-m pgvector` | Postgres running + corpus loaded |
| `-m llm` | Groq/Google keys (calls are cached after the first run) |

---

## Phase 0 — Setup

```bash
python scripts/check_setup.py
```

Pings both databases, the `vector` extension, the local embedding model, and both
LLM providers.

```
[ok] Neo4j        bolt://localhost:7687
[ok] Postgres     pgvector extension present
[ok] Embeddings   BAAI/bge-small-en-v1.5  (dim 384)
[ok] Groq         openai/gpt-oss-120b
[ok] Google       gemini-3.6-flash

Phase 0 gate: PASS
```

---

## Phase 1 — Knowledge graph

### 1.1–1.3  Models, chunking, extraction (offline tests)

```bash
pytest tests/test_models.py tests/test_chunk.py tests/test_extract.py -m "not llm"
```

```
tests/test_models.py ...................................  [ 41%]
tests/test_chunk.py ...............                       [ 59%]
tests/test_extract.py ..................                  [100%]

66 passed
```

The `-m llm` tests in `test_extract.py` do a real (cached) extraction of three
service documents and check the retry-on-invalid-JSON path.

### 1.4  Build the graph

```bash
python scripts/ingest_corpus.py --wipe
```

Chunks the corpus, extracts entities and relationships (cache hits, no API
calls), resolves aliases and duplicates, and `MERGE`s everything into Neo4j and
pgvector.

```
=== ingest summary ===
chunks: 42   extracted ok: 42   deferred: 0   failed: 0
entities: 43   relationships: 222
edges missing evidence/source: 0
edges skipped (bad endpoint): 0
vectors: 42 chunks embedded (384-dim, local)
elapsed: 2.0 min

entities by type:
  Service            8
  API                6
  Library            5
  ...
relationships by type:
  DEPENDS_ON         44
  USES               37
  OWNED_BY           27
  ...

Phase 1.4 gate: CHECK
```

`CHECK` means the counts are just outside the originally planned ranges (43
entities vs. 45–65; 222 edges vs. 140–200). Both are explained in the summary and
in the main README appendix — the corpus really has 43 distinct entities, and
edges are keyed on `source_chunk_id` for provenance.

Re-run it — the counts do not change. That is the idempotency guarantee.

```bash
pytest tests/test_resolve.py tests/test_load_graph.py -m "not neo4j"
python scripts/ingest_corpus.py --wipe        # run twice; same 43 / 222
```

> **Note.** `pytest -m neo4j` includes `test_load_graph.py`, which wipes and
> rebuilds Neo4j. After running the full marked suite, re-run
> `python scripts/ingest_corpus.py --wipe` to restore the index.

---

## Phase 2 — Vector index

### 2.1–2.2  Embed, store, recall check

```bash
pytest tests/test_load_vector.py tests/test_retrieve_vector.py -m "not pgvector"
```

```
9 passed
```

The `pgvector` gates:

```bash
pytest tests/test_retrieve_vector.py -m pgvector
```

```
tests/test_retrieve_vector.py::test_vector_retrieval_gate PASSED
tests/test_retrieve_vector.py::test_recall_at_5_clears_the_gate PASSED

2 passed
```

`test_recall_at_5_clears_the_gate` runs 12 definitional questions through
`retrieve_vector` and checks the gold chunk lands in the top 5. Result: recall@1
is 1.00 — with ~42 distinct-topic vectors and an exact scan, the nearest chunk is
the right chunk, which is exactly why there is no ANN index.

> `test_load_vector.py -m pgvector` rebuilds the `meridian_chunks` collection —
> re-run the ingest afterwards.

---

## Phase 3 — Routing and retrieval

### 3.1  Router

```bash
pytest tests/test_router.py -m "not llm"          # confidence-floor + fixture hygiene
pytest tests/test_router.py -m llm                # accuracy gate (cached)
```

```
tests/test_router.py::test_router_accuracy_clears_the_gate PASSED
```

Accuracy is 95.2% on 21 labelled questions disjoint from the few-shot examples.
`ROUTING_METRICS.md` is a committed snapshot of one run's confusion matrix.

### 3.2  Graph retriever

```bash
pytest tests/test_retrieve_graph.py -m "not llm and not neo4j"   # pure + fake-client
pytest tests/test_retrieve_graph.py -m "llm and neo4j"           # gate: B09/B14/B16/B17/B24
```

```
tests/test_retrieve_graph.py::test_graph_retrieval_gate PASSED
```

The gate checks that each question returns the exact set of gold nodes and that
the Cypher runs in under 200 ms (it runs in 12–56 ms).

### 3.3  Vector retriever

Covered in Phase 2 above (`test_retrieve_vector.py`).

### 3.4  Merge and pipeline

```bash
pytest tests/test_merge.py tests/test_pipeline.py
```

```
14 passed
```

`test_pipeline.py` exercises every route and both fallback edges (graph empty →
vector, nothing retrieved → REFUSE) with fake retrieval functions.

---

## Phase 4 — Synthesis and API

### 4.1  Synthesize

```bash
pytest tests/test_synthesize.py -m "not llm"      # stub model
pytest tests/test_synthesize.py -m llm            # gate: 5 sample answers (cached)
```

```
tests/test_synthesize.py::test_synthesis_gate PASSED
```

Every sample answer is non-empty, has at least one citation, and every cited
`chunk_id` is in the retrieved set.

### 4.2  Validate citations

```bash
pytest tests/test_validate.py -m "not llm"        # regeneration logic
pytest tests/test_validate.py -m llm              # gate: 100% validity + injection catch
```

```
tests/test_validate.py::test_validation_gate PASSED
```

### 4.3  API

```bash
pytest tests/test_api.py -m "not llm"             # 400 / 422 / 503 / health, stubbed
pytest tests/test_api.py -m llm                   # gate: one real request per route
```

```
tests/test_api.py::test_api_gate PASSED
```

Then run it for real:

```bash
uvicorn src.api.main:app
curl -s localhost:8000/query -H 'content-type: application/json' \
  -d '{"question": "Which services use PostgreSQL?"}' | python -m json.tool
```

```json
{
  "question": "Which services use PostgreSQL?",
  "answer": "Auth Service, Billing Service, Ledger Service, Reporting Service, and User Service use PostgreSQL.",
  "citations": [ ... ],
  "routing_used": "GRAPH",
  "latency_ms": 7773
}
```

An out-of-scope question returns `422`:

```bash
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/query \
  -H 'content-type: application/json' \
  -d '{"question": "Is PostgreSQL better than MySQL?"}'
# 422
```

---

## Phase 5 — Benchmark

### 5.1  Run both systems

```bash
python scripts/benchmark.py
```

Runs all 14 benchmark questions through the graph pipeline and the vector-only
baseline. Writes `tests/fixtures/benchmark_run.json` after every call, so it
resumes if interrupted (the free-tier quota will not finish it in one pass on a
cold cache). To run a subset:

```bash
python scripts/benchmark.py --questions B17,B24,B28
```

```
ran 14 questions x 2 system(s)
raw -> benchmark_run.json   grading skeleton -> BENCHMARK_RESULTS.md
```

### 5.2  Score

`BENCHMARK_RESULTS.md` already carries the manual grades. Recompute the category
means and gate:

```bash
python scripts/score_benchmark.py
```

```
=== benchmark scores ===
category       graph  vector   delta  gate
1-hop           0.84    0.84   +0.00 [  ok ] |delta|=0.00 <= 0.05
2-hop           1.00    1.00   +0.00 [ FAIL] delta=+0.00 >= 0.15
3-hop           0.75    0.75   +0.00 [ FAIL] delta=+0.00 >= 0.3  (1 ungraded)
aggregation     1.00    1.00   +0.00 [ FAIL] graph=1.00>=0.8, vector=1.00<=0.2
refusal         1.00    1.00   +0.00 [  ok ] not gated

Phase 5.2 gate: INCOMPLETE / FAIL
```

The `FAIL` rows are the finding, not a bug. See [`../FINDINGS.md`](../FINDINGS.md).

```bash
pytest tests/test_benchmark.py                    # parser + scorer, offline
```

---

## Everything at once

```bash
# offline — fast, no external services
pytest -m "not llm and not neo4j and not pgvector"
# -> 237 passed

# gates — needs containers + keys (cached calls)
pytest -m "llm or neo4j or pgvector"
# then restore the indexes, since some marked tests wipe them:
python scripts/ingest_corpus.py --wipe
```
