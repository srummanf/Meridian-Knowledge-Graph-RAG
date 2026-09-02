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

### 1.4 Graph load + resolution — 42/42 chunks live
`src/ingest/resolve.py` (normalise → alias table → dedupe → deterministic id),
`src/graph/queries.py` (11 entity + 12 relationship MERGE templates, built from
the enums), `src/graph/client.py` (`Neo4jGraph` + constraint/index setup),
`src/ingest/load_graph.py` (node `properties` → JSON string; `HANDLES` → `:Concern`
node). `scripts/ingest_corpus.py` runs chunk→extract→resolve→load (`--wipe` for a
clean rebuild; pauses cleanly, exit 2, when both LLM providers are throttled).
All unit/integration tests pass.

**Free-tier constraint (2026-09-02):** Groq free tier caps a single request at
8000 TPM; ~8 of the larger chunks exceed that (prompt + schema + output ≈ 9.5k)
and go through Gemini. `extract.py` distinguishes a `413` from real throttling
and switches those chunks to Google-only. Three chunks
(`user-service.md#overview`/`#security`, `data-team.md`) were parked in
`DEFERRED_CHUNKS` while both daily quotas were spent; their cached extractions
were later recovered (a one-off dropped one malformed relationship — missing
`confidence`/`evidence` — from the third's cached response) and folded back in.
`DEFERRED_CHUNKS` is now empty and the whole corpus rebuilds from cache, $0.

**Gate met (42/42):**
- Neo4j: **43 entities, 222 relationships**. Entities sit just under the 45–65
  target — the corpus genuinely resolves to 43 distinct nodes. Edges are keyed on
  `source_chunk_id`, so a fact in N chunks = N edges (provenance); the raw count
  is above the 140–200 band for the same reason (distinct `(src,type,tgt)` ≈ 130).
- Every `ONTOLOGY.md` §3 alias case → one node. ✅
- Re-running `ingest_corpus.py` changes no counts. ✅ (43 / 222 both runs)
- Every relationship has `source_chunk_id` + `evidence`. ✅ (0 missing)
- Ingest < 20 min, $0. ✅ (~2 min, all cache hits)

### 1.5 Extraction eval
Hand-label the ~25 benchmark-critical relationships (from
`data/benchmark/questions.md`) as gold. `scripts/eval_extraction.py` →
precision/recall/F1. **Gate:** entity F1 ≥ 0.85, relationship F1 ≥ 0.75; revise
prompt + re-run if lower. **Files:** `EXTRACTION_METRICS.md`.

---

## Phase 2 — Vector index (2 days)

### 2.1 Embed + store ✅ (built)
`src/ingest/load_vector.py` — `HuggingFaceEmbeddings("BAAI/bge-small-en-v1.5")`
(local), `PGVector.add_documents(ids=[chunk_id])` (upsert → idempotent) with
metadata `{chunk_id, document, entity_ids}`, collection `meridian_chunks`, cosine,
384-dim, no ANN index. Wired into `ingest_corpus.py`. **Gate met:** all **42**
chunks embedded (384-dim, verified in `langchain_pg_embedding`); `chunk_id` is the
shared key across Neo4j + pgvector; re-run changes nothing.
`tests/test_load_vector.py` (4 unit + 2 `@pytest.mark.pgvector`).

### 2.2 Recall sanity check ✅
`tests/fixtures/vector_eval.json` — 12 `(question → gold chunk_id)` pairs (8 from
the benchmark's VECTOR set). `tests/test_retrieve_vector.py::test_recall_at_5_clears_the_gate`
runs them through `retrieve_vector` and measures recall@5.
**Gate met:** recall@1 = **1.00** (n=12), well over the 0.9 recall@5 bar. Why no
ANN index (docstring in `test_retrieve_vector.py`): ~42 vectors, exact scan is
sub-ms and recall-1.0 by construction; HNSW/IVFFlat only pay off 3–5 orders of
magnitude larger and would add approximation error.

---

## Phase 3 — Pipeline: routing & retrieval (1 week)

### 3.1 Router ✅ (built)
`src/pipeline/router.py` — `router_model.with_structured_output(RoutingDecision)`,
12-example few-shot (10 from `data/benchmark/questions.md`). `conf < 0.70 →
HYBRID`. Logs every decision. **Gate met:** **95.2%** (20/21) on
`tests/fixtures/routing_eval.json` (21 labelled questions, disjoint from the
few-shot). Confusion matrix in the committed `ROUTING_METRICS.md` snapshot; the
single miss is a GRAPH/VECTOR borderline ("what does the Billing Service depend
on?"). `tests/test_router.py` (unit + `@pytest.mark.llm` gate).

### 3.2 Graph retriever ✅
`src/pipeline/retrieve_graph.py` — one structured-output call fills a
`GraphQueryPlan` (the model never writes Cypher) → resolve anchors → pick a
generic read template → `Neo4jGraph.query()` → per-relationship-type sentences.
Templates (`src/graph/queries.py`): `RESOLVE_ENTITY(_FUZZY)`, `NEIGHBORS`,
`COUNT_NEIGHBORS`, `TWO_CONSTRAINT`, `PATH_BETWEEN` (`shortestPath ≤5`),
`BLAST_RADIUS` (variable-length). The rel type is a `$rel` parameter, not
interpolated. **Gate met:** B09/B14/B16/B17/B24 exact node sets; Cypher 12–56 ms
(< 200). `tests/test_retrieve_graph.py` + `tests/fixtures/graph_eval.json`.

### 3.3 Vector retriever ✅
`src/pipeline/retrieve_vector.py` — one `PGVector.similarity_search_with_score`
(exact cosine, no HNSW), top-k `Passage`s, `score` = raw cosine distance. No LLM
call. **Gate met:** B01–B08 all rank 1 in top-3.
`tests/fixtures/vector_retrieval_eval.json`, `tests/test_retrieve_vector.py`.

### 3.4 Merge + graph wiring ✅
`src/pipeline/merge.py` — `merge()` dedupes passages (best score per `chunk_id`,
then `SequenceMatcher ≥ 0.95` near-duplicate bodies) and graph facts, unions the
source ids; `labelled_context()` writes `GRAPH FACTS` / `RETRIEVED PASSAGES`
headers. `src/pipeline/graph.py` — LangGraph `StateGraph`: `route` → conditional
→ `retrieve_graph` / `retrieve_vector` → `merge`, with fallbacks (HYBRID or
graph empty → vector; nothing retrieved → REFUSE). Linear even for HYBRID.
`compile_pipeline(router, graph_fn, vector_fn)` injects retrieval for tests;
`run_pipeline(q)` is the singleton entry point. **Gate met:** every route + both
fallbacks covered; end-to-end smoke on all four routes.
`tests/test_merge.py` (7), `tests/test_pipeline.py` (7).

---

## Phase 4 — Synthesis & API (3 days)

### 4.1 Synthesize ✅
`src/pipeline/synthesize.py` — one `chat_model.with_structured_output(SynthesisResult)`
call over the `GRAPH FACTS` / `RETRIEVED PASSAGES` labelled context; a
`Citation{claim, chunk_id, source_type}` per claim, chunk id copied from a
`[bracket]`. Empty context → fixed no-answer, no call. **Gate met:** 5/5 sample
answers coherent + every citation in the retrieved set.
`tests/test_synthesize.py`.

### 4.2 Validate citations ✅
`src/pipeline/validate.py` — `validate_answer()`: all cited ids in
`context.chunk_ids` → unchanged; else regenerate **once** with a
`Cite ONLY from: […]` allow-list, keep the valid citations, note the drop.
`graph.py::compile_answer_pipeline` wires retrieval subgraph → `synthesize` →
`validate` (REFUSE skips to END); `answer_question(q)` is the singleton.
**Gate met:** 100% validity on the sample; injected bad citation removed.
`tests/test_validate.py`.

### 4.3 API + end to end ✅
`src/api/{main,schemas,dependencies}.py` — `POST /query` (200 `GroundedAnswer` /
422 out-of-scope / 400 bad input / 503 DB down via `require_datastores`),
`GET /health`. Invokes `answer_question`. **Gate met:** one integration test per
route (VECTOR/GRAPH/HYBRID/REFUSE). Latency table in `API_METRICS.md` (measured
warm — cold free-tier calls add 5–120 s of rate-limit back-off, not
representative; `API_METRICS.md` is a committed snapshot). `tests/test_api.py`.

---

## Phase 5 — Benchmark & writeup (4–5 days)

### 5.1 Baseline + harness ✅ (built; run in progress)
`src/baselines/vector_only.py` — `answer_vector_only()` = `compile_answer_pipeline`
with the router pinned to `VECTOR`, so the graph node never runs (everything else
held constant). `scripts/benchmark.py` parses `data/benchmark/questions.md` →
`tests/fixtures/benchmark_questions.json` (30 Qs, category/route/gold/sources),
runs each through both systems, and writes `tests/fixtures/benchmark_run.json`
(**incrementally + resumable** — free-tier quota will not finish it in one pass)
+ a grading skeleton to `BENCHMARK_RESULTS.md` (answer, route, latency, est.
tokens, citations, notes per system). `tests/test_benchmark.py` (parser + scorer).

### 5.2 Grade + analyse ✅ — gate NOT met; that is the finding
Question set scoped to **14** (`questions.md` § Scope). Grades in
`BENCHMARK_RESULTS.md`; `scripts/score_benchmark.py` means + gate check.
**Result:** 1-hop parity (0.84 / 0.84) ✅; 2-hop / 3-hop / aggregation all
**Δ = 0.00** — the graph did not beat vector-only. Causes: (1) the corpus
pre-aggregates relationships (hub docs list their consumers + state counts), so
vector answers nominal multi-hop from one doc; (2) B18's true 3-hop chain fits
none of the six `GraphQueryPlan` templates → planner failed. Graph's real edge:
citation granularity + refusal routing. Full analysis in `FINDINGS.md`.

### 5.3 Writeup ✅
- `README.md`: benchmark table at the top.
- `FINDINGS.md`: corpus pre-aggregation, template ceiling, where the graph
  wins/loses, latency & cost honesty, *why not `GraphCypherQAChain`*.
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

Resume line:

> Built a hybrid knowledge-graph + vector RAG system (LangGraph, Neo4j, pgvector,
> Groq) over a 37-document corpus: LLM router, a security-reviewed Cypher-template
> retriever (no model-authored queries), and a citation validator that holds
> 100% cited-source validity. Benchmarked it head-to-head against a vector-only
> baseline and reported the honest result — parity on this corpus, because the
> source docs pre-aggregate their relationships, plus a template-coverage ceiling
> on true multi-hop questions.
