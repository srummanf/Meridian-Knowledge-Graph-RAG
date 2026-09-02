# Phases — Meridian Knowledge Graph RAG

**Version:** 3.0 · **Updated:** 2026-09-01 · ~2–3 weeks part-time

Rapid prototype: LangChain for plumbing, LangGraph for the query pipeline,
hand-built router + Cypher retrieval + citation validator. Five phases; each has
tasks, a gate, and the files it produces. Graph-size numbers come from
`data/ONTOLOGY.md` §6.

---

## Phase 0 — Setup (½ day)

**Tasks**
- `pyproject.toml`: `langchain`, `langchain-core`, `langgraph`, `langchain-groq`,
  `langchain-google-genai`, `langchain-huggingface`,
  `langchain-postgres`, `langchain-neo4j`, `langchain-text-splitters`,
  `sentence-transformers`, `neo4j`, `psycopg[binary]`, `pgvector`, `fastapi`,
  `uvicorn`, `pydantic`, `pydantic-settings`, `python-dotenv`, `pytest`, `ruff`.
- `docker-compose.yml`: Neo4j 5 Community + Postgres 16 w/ `pgvector`, health
  checks, named volumes.
- `.env.example` (see `architecture.md` §2). `src/config.py` — settings +
  `chat_model()` / `router_model()` / `embeddings()` factories +
  `set_llm_cache(SQLiteCache("cache/llm.db"))`. `src/logging_config.py`.
- Free Groq API key; Google AI Studio key as fallback.

**Gate:** `docker-compose up` → both DBs healthy; `chat_model().invoke("ping")`
returns text via Groq and via Google.

**Files:** `pyproject.toml`, `docker-compose.yml`, `.env.example`,
`src/config.py`, `src/logging_config.py`

---

## Phase 1 — Knowledge graph construction (1 week)

### 1.1 Models
`src/models/{domain,extraction,routing,answer}.py` per `architecture.md` §4.
Enums match `ONTOLOGY.md` exactly. **Gate:** models validate good data, reject
bad (unknown enum, out-of-range confidence).

### 1.2 Chunking
`src/ingest/chunk.py` — `MarkdownHeaderTextSplitter`; one chunk per document,
split by `##` only if a doc exceeds **~280 tokens** (no doc in the final corpus
reaches the original ~350 estimate; largest ≈ 289). When a doc splits, `##`
sections are *packed* greedily into ~250-token sub-chunks, not one-per-heading.
Assign `chunk_id = "<relpath>"` / `"<relpath>#<slug-of-first-section>"`.
**Gate:** 37 docs → **40–55 chunks** (currently 42), unique ids, non-empty
content.

### 1.3 Extraction ✅
`src/ingest/extract.py` — prompt built from `ONTOLOGY.md` §1–§3 + the `SCHEMA.md`
§5 example (§4–§5 folded into the task instructions to save tokens);
`chat_model.with_structured_output(ExtractionResult)` — **Groq uses
`method="json_schema"`** (`gpt-oss` rejects the default `function_calling`).
Validation (enum, evidence-substring, confidence floor, property-subset,
endpoint-in-chunk) with ≤3 retry feeding the errors back; unparseable responses
also retried; exhausted chunks recorded in `failed`, not raised. Relies on
`SQLiteCache`. **Gate:** clean run on `auth-service`, `ledger-service`,
`payments-platform` (`tests/test_extract.py -m llm`); corrupted response rejected
+ retried; second run is a cache hit (SQLite row count unchanged).
Note: Groq free-tier TPM limits make a full 42-chunk run take ~5–20 min with
back-offs — acceptable for a one-time ingest.

### 1.4 Graph load + resolution — 39/42 chunks live, gate PROVISIONAL
`src/ingest/resolve.py` (normalise → alias table → dedupe → deterministic id),
`src/graph/queries.py` (11 entity + 12 relationship MERGE templates, built from
the enums), `src/graph/client.py` (`Neo4jGraph` + constraint/index setup),
`src/ingest/load_graph.py` (node `properties` → JSON string; `HANDLES` → `:Concern`
node). `scripts/ingest_corpus.py` runs chunk→extract→resolve→load (`--wipe` for a
clean rebuild; pauses cleanly, exit 2, when both LLM providers are throttled).
`scripts/backfill_extract.py` seeds the cache for oversized chunks via Gemini.
All unit/integration tests pass.

**Free-tier constraint (2026-09-02):** Groq free tier caps a single request at
8000 TPM; ~8 of the larger chunks exceed that (prompt + schema + output ≈ 9.5k)
and must go through Gemini. `extract.py` now distinguishes a `413` from real
throttling and switches those chunks to Google-only. A day of debugging
exhausted both free daily quotas and cost the Gemini cache for 3 chunks, so they
sit in `ingest_corpus.py::DEFERRED_CHUNKS` (`user-service.md#overview`,
`user-service.md#security`, `data-team.md`).

**To finish:** after quotas reset — `python scripts/backfill_extract.py`, then
clear `DEFERRED_CHUNKS`, then `python scripts/ingest_corpus.py --wipe`.

**Gate:**
- Neo4j: **45–65 distinct entities**, **140–200 relationships**.
  Provisional (39/42): **43 entities, 202 relationships**. Edges are keyed on
  `source_chunk_id`, so a fact in N chunks = N edges (provenance); distinct
  `(src,type,tgt)` ≈ 125.
- Every `ONTOLOGY.md` §3 alias case → one node.
- Re-running `ingest_corpus.py` changes no counts. ✅ (43 / 202 both runs)
- Every relationship has `source_chunk_id` + `evidence`. ✅ (0 missing)
- Ingest < 20 min, $0. ✅ (~2 min, all cache hits)

### 1.5 Extraction eval
Hand-label the ~25 benchmark-critical relationships (from
`data/benchmark/questions.md`) as gold. `scripts/eval_extraction.py` →
precision/recall/F1. **Gate:** entity F1 ≥ 0.85, relationship F1 ≥ 0.75; revise
prompt + re-run if lower. **Files:** `EXTRACTION_METRICS.md`.

---

## Phase 2 — Vector index (2 days)

### 2.1 Embed + store
`src/ingest/load_vector.py` — `HuggingFaceEmbeddings("BAAI/bge-small-en-v1.5")`
(local), `PGVector.add_documents` with metadata `{chunk_id, document,
entity_ids}`. Extend `ingest_corpus.py`. **Gate:** all chunks embedded (384-dim);
a `chunk_id` resolves in both Neo4j and pgvector.

### 2.2 Recall sanity check
`tests/fixtures/vector_eval.json` — ~10 `(question → gold chunk_id)` pairs.
`PGVector.similarity_search`, measure recall@5. **Gate:** recall@5 ≥ 0.9
(expect ≈ 1.0). One paragraph on why ANN indexing is unnecessary here.

---

## Phase 3 — Pipeline: routing & retrieval (1 week)

### 3.1 Router
`src/pipeline/router.py` — `router_model.with_structured_output(RoutingDecision)`,
few-shot (3–4 per class from `data/benchmark/questions.md`). `conf < 0.70 →
HYBRID`. Log every decision. **Gate:** ≥ 90% on a ~20-question labelled set;
`ROUTING_METRICS.md` with confusion matrix.

### 3.2 Graph retriever
`src/pipeline/retrieve_graph.py` — LLM entity-mention extraction → resolve →
choose read template → `Neo4jGraph.query()` → paths → sentences (per-type string
templates). Read templates: `entity_by_name`, `neighbors_1hop`, `path_2hop`,
`two_constraint`, `count_by_relationship`, `blast_radius` (variable-length),
`owned_by_chain`. **Gate:** B09, B14, B16, B17, B24 return correct node sets;
≤3-hop query < 200 ms.

### 3.3 Vector retriever
`src/pipeline/retrieve_vector.py` — `PGVector.similarity_search_with_score`,
top-k passages. **Gate:** B01–B08 return the expected source chunk in top-3.

### 3.4 Merge + graph wiring
`src/pipeline/merge.py` (dedupe on chunk_id + near-duplicate text).
`src/pipeline/graph.py` — LangGraph `StateGraph`: `route` → conditional →
`retrieve_graph` / `retrieve_vector` / both → `merge`, with fallback edges
(graph empty → vector; vector empty → REFUSE). **Gate:** pipeline runs end to
end returning a merged context object for each route; unit test on a crafted
overlapping set.

---

## Phase 4 — Synthesis & API (3 days)

### 4.1 Synthesize
`src/pipeline/synthesize.py` + prompt — labelled context in, cited answer out,
citation per claim. **Gate:** 5 sample answers coherent, every claim has a
`chunk_id`.

### 4.2 Validate citations
`src/pipeline/validate.py` — every cited `chunk_id` ∈ retrieved set; regenerate
once with an allow-list on failure. Wire as the final LangGraph node. **Gate:**
injected bad citation caught; 100% validity across the benchmark.

### 4.3 API + end to end
`src/api/main.py` (`POST /query`, `GET /health`), `dependencies.py`. Invoke the
compiled LangGraph. **Gate:** one integration test per route passes; p95 latency
recorded (target < 3 s, soft).

**Files:** `src/api/*`, `tests/test_integration.py`

---

## Phase 5 — Benchmark & writeup (4–5 days)

### 5.1 Baseline + harness
`src/baselines/vector_only.py` — same pipeline, `route` forced to VECTOR, graph
nodes skipped. `scripts/benchmark.py` reads `data/benchmark/questions.md`
(convert to `tests/fixtures/benchmark_questions.json`), runs both systems,
records per question: answer, latency, tokens, cited sources.

### 5.2 Grade + analyse
Manual grading, rubric in `data/benchmark/questions.md` (0 / .25 / .5 / .75 / 1).
Accuracy by category (1-hop, 2-hop, 3-hop, aggregation, refusal). **Gate:**
- 1-hop: Graph within ±5% of vector.
- 2-hop: Graph ≥ +15%.
- 3-hop / multi-constraint: Graph ≥ +30%.
- Aggregation: Graph ≥ 80%, vector ≈ 0%.
- Reproducible from the script.

### 5.3 Writeup
- `README.md`: benchmark table on top → architecture diagram → quick start.
- `FINDINGS.md`: why vector-only fails at multi-hop; where graph wins/loses;
  latency & cost honesty; *why not `GraphCypherQAChain`*; how you'd productionise.
- `SETUP.md`: local dev.

**Files:** `src/baselines/vector_only.py`, `scripts/benchmark.py`,
`BENCHMARK_RESULTS.md`, `README.md`, `FINDINGS.md`, `SETUP.md`

---

## Timeline

| Phase | Duration | Milestone |
|-------|----------|-----------|
| 0 | ½ day | DBs up, both LLM providers reachable |
| 1 | 1 wk | Neo4j populated, idempotent, F1 ≥ 0.85 |
| 2 | 2 d | pgvector populated, recall sane |
| 3 | 1 wk | router ≥ 90%, LangGraph pipeline runs all routes |
| 4 | 3 d | `/query` end to end, 100% valid citations |
| 5 | 4–5 d | benchmark table, findings, README |

Resume line (fill X/Y/Z from Phase 5):

> Built a hybrid knowledge-graph + vector RAG system (LangGraph, Neo4j, pgvector,
> Groq) over a 37-document technical corpus; raised 3-hop question accuracy from
> X% to Y% vs. a vector-only baseline at Z ms p95, with 100% citation validity.
