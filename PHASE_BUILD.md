# Phase Build Log

A running map of **what each file is and why it exists**, phase by phase. Updated
as files land. Spec lives in `prd.md` / `architecture.md` / `rules.md` /
`phases.md`; this file is the "what am I looking at" index.

Legend: ✅ done · 🚧 in progress · ⬜ not started

---

## Phase 0 — Setup ✅

Goal: both databases running, both LLM providers reachable, config in one place.

| File | What it does |
|------|--------------|
| `pyproject.toml` | Package + dependency list (LangChain/LangGraph, Neo4j, pgvector, FastAPI, pytest, ruff). Installed with `pip install -e ".[dev]"`. |
| `docker-compose.yml` | Runs Neo4j 5 (`7474`/`7687`) and Postgres 16 + pgvector (host `5433` → container `5432`) with health checks and named volumes. |
| `.env.example` | Template for `.env`: DB DSNs + the two API keys + model IDs. Copy to `.env` and fill the keys. |
| `src/config.py` | **The only file that builds provider classes.** `Settings` (from `.env`), plus factories `chat_model()` / `router_model()` / `embeddings()` with Groq→Google fallback, and the SQLite LLM cache. |
| `src/logging_config.py` | One stdout log handler, consistent format, quiets noisy libraries. `configure_logging()` / `get_logger()`. |
| `scripts/check_setup.py` | Phase 0 gate: pings Neo4j, Postgres (+ checks `vector` extension), local embeddings (384-dim), and both LLM providers. Prints PASS/FAIL. |

**Concept:** all I/O boundaries (DBs, LLMs, embeddings) are wrapped once so the
rest of the code never imports a provider SDK directly.

---

## Phase 1 — Knowledge graph construction

### 1.1 Models ✅

Goal: typed, validated shapes for everything that flows through the pipeline.
Vocabulary matches `data/ONTOLOGY.md` exactly.

| File | What it does |
|------|--------------|
| `src/models/domain.py` | The graph vocabulary. `EntityType` (11), `RelationType` (12), `DataConcern` (5 controlled strings for `HANDLES`). `Entity` / `Relationship` models with `confidence ∈ [0,1]`. `slugify()` + `make_entity_id()` build the deterministic IDs (`service:auth-service`). `RELATION_PROPERTY_KEYS` = which properties each edge type may carry. `CONFIDENCE_FLOOR = 0.80`. |
| `src/models/extraction.py` | `ExtractionResult` = `{entities, relationships}`. This is the schema handed to `chat_model.with_structured_output(...)` — the LLM fills it in per chunk. |
| `src/models/routing.py` | `RoutingDecision` = `{route, confidence, reasoning, entities_detected}`. `route ∈ {VECTOR, GRAPH, HYBRID, REFUSE}`. `HYBRID_CONFIDENCE_FLOOR = 0.70`. |
| `src/models/answer.py` | `Passage` (a retrieved vector chunk), `Citation` (claim ↔ source), `GroundedAnswer` (the `POST /query` response). |
| `src/models/__init__.py` | Flat re-exports so callers do `from src.models import Entity`. |
| `tests/test_models.py` | Gate: models accept valid data, reject unknown enums and out-of-range confidence. 35 tests. |

**Concept:** `source_chunk_id` defaults to `""` — the LLM never sets it, the
ingest pipeline stamps it from the chunk being processed. Every fact in the graph
must trace back to a chunk.

### 1.2 Chunking ✅

Goal: turn 37 Markdown docs into ~40–55 retrieval/extraction units with stable IDs.

| File | What it does |
|------|--------------|
| `src/ingest/chunk.py` | `Chunk` model (`chunk_id`, `document`, `content`). `chunk_corpus()` walks `data/**/*.md` (skips `ONTOLOGY`/`SCHEMA`/`README`/`benchmark`). One chunk per doc; a doc over ~280 est. tokens (`chars/4`) is split on `##` headings, then sections are *packed* into ~250-token sub-chunks. IDs: `services/auth-service.md` or `services/billing-service.md#overview`. Produces **42 chunks**. |
| `tests/test_chunk.py` | Gate: 37 docs → 40–55 chunks, unique IDs, non-empty content, split docs cover all their sections. 15 tests. |

**Concept:** whole-doc chunks are the default because each doc describes exactly
one entity — that keeps extraction evidence and citations clean. Splitting is the
exception for the few long service docs.

### 1.3 Extraction ✅

Goal: turn each chunk into validated entities + relationships with an LLM,
cheaply and reproducibly.

| File | What it does |
|------|--------------|
| `src/utils/errors.py` | One exception hierarchy. `ApplicationError` base; `ExtractionError` (retries exhausted), `LLMUnavailableError`, `GraphUnavailableError`, `RetrievalError`. The API layer maps these to HTTP codes. |
| `src/utils/__init__.py` | package marker |
| `src/ingest/extract.py` | `extract_chunk(chunk)` — builds a system prompt from `ONTOLOGY.md` §1–3 + the `SCHEMA.md` example, calls `chat_model.with_structured_output(ExtractionResult)`, drops rows below confidence 0.80, then `_validate()` checks evidence-is-a-substring, allowed properties, and that every relationship endpoint is an entity from the same chunk. On failure it retries ≤3× feeding the errors back to the model, then raises `ExtractionError`. `extract_corpus(chunks)` runs all chunks, collecting failures into a `failed` list instead of aborting. `_stamp()` writes `source_chunk_id` onto every row. |
| `tests/test_extract.py` | 20 unit tests (stub model — no API) for validation + retry, plus 4 `@pytest.mark.llm` gate tests: clean extraction on auth-service / ledger-service / payments-platform, and a cache-hit check. |

**Concept:** the LLM never touches the database and its output is never trusted
raw — every field is validated, and `evidence` must be a real substring of the
chunk so citations can't be hallucinated. `config.py` change: Groq needs
`with_structured_output(..., method="json_schema")` — `gpt-oss` rejects the
default tool-calling method.

### 1.4 Graph load + resolution ✅ (42/42 chunks live)

Goal: resolve the per-chunk extractions into one clean graph and MERGE it into Neo4j.

| File | What it does |
|------|--------------|
| `src/ingest/resolve.py` | `resolve(results)` → `(entities, relationships)`. Per entity: strip a leading article, peel a trailing version into `properties.version`, look up the `ONTOLOGY.md` §3 alias table (a hit replaces name **and** type), recompute the deterministic id, then merge entities that now share an id. Per relationship: re-point both endpoints at a resolved entity by name, map `HANDLES` targets to `concern:<slug>`, drop self-loops, store `ALTERNATIVE_TO` one direction, then merge edges sharing `(source, type, target, source_chunk_id)`. Pure and deterministic. |
| `src/graph/queries.py` | Every Cypher string. `SCHEMA_STATEMENTS` (id constraints + name/type indexes), `WIPE`, 11 `ENTITY_TEMPLATES` (one per type — Cypher can't parameterise a label), 12 `RELATIONSHIP_TEMPLATES` (one per type, keyed on `source_chunk_id`; `HANDLES` targets a `:Concern` node), and count queries for gate checks. Templates are built once from the enums — the only place a type name is formatted into a string. |
| `src/graph/client.py` | `graph_client()` — the shared `Neo4jGraph` (one driver/process). `ensure_schema()`, `wipe()`. |
| `src/ingest/load_graph.py` | `load_graph(entities, relationships)` — MERGE each entity (its `properties` map is JSON-serialised because Neo4j properties must be primitive; `version` hoisted out), then each relationship via its template. Returns live DB counts. All MERGE → re-running changes nothing. |
| `scripts/ingest_corpus.py` | `chunk_corpus() → extract_corpus(skip=DEFERRED_CHUNKS) → resolve() → load_graph() → load_vector()`. `--wipe` for a clean rebuild. Prints the summary + type breakdowns and checks the gate ranges. `DEFERRED_CHUNKS` is now empty; still pauses cleanly (exit 2) if a chunk finds both providers rate-limited. |
| `scripts/backfill_extract.py` | One-off: extract the oversized chunks through **Gemini only** and write the result into `cache/llm.db` as the *first-attempt* Google cache row, so a normal Groq-primary ingest cache-hits the Google fallback leg. Never deletes a row. |
| `scripts/repair_cache_rows.py` | One-off: drop malformed rows (missing required fields) from a cached extraction *response*, in place, keeping the cache key. Fixed `user-service.md#overview` — its cached response had one relationship missing `confidence`/`evidence`, which made the structured-output parser reject the whole response and `extract_chunk` retry live every ingest. Backs the original row up to `cache/llm.db.repair-backup.*.jsonl`; idempotent. |
| `tests/test_resolve.py` (39) · `tests/test_queries.py` (8) · `tests/test_load_graph.py` (6, 3 `@pytest.mark.neo4j`) | |

**Concept:** resolution is where "the gateway", "api-gw", "edge gateway" all
become the one node `service:api-gateway`. Determinism + MERGE-on-deterministic-id
is what makes re-ingesting a no-op.

`config.py` also gained `extract_model()` + `GROQ_EXTRACT_MODEL` — extraction is a
token-heavy batch, so it can run on a different Groq model (hence a separate daily
token quota) from synthesis. `extract_model(..., only="google")` pins to one
provider with no fallback.

**Free-tier reality (2026-09-02).** Groq's free tier rejects any single request
over **8000 tokens/minute** with a `413 "request too large"` — a handful of the
larger chunks (prompt + JSON schema + output reservation ≈ 9.5k) can never go
through Groq there. Fix: `extract.py` now tells a `413` apart from real
throttling (`_is_request_too_large`) and, for that chunk only, switches to
Google-only for its remaining retries instead of aborting the batch. The 8
oversized chunks were extracted via Gemini and cached.

A day of iterative debugging then burned **both** free daily quotas (Groq 200K
tokens; Gemini 20 requests), leaving 3 chunks parked in `DEFERRED_CHUNKS`. Their
cached extractions were later recovered — 2 already cache-hit cleanly, and
`repair_cache_rows.py` fixed the malformed relationship in the third — so the
full corpus is now in the graph: **all 42 chunks, 43 entities / 222
relationships**, idempotent, `$0`, ~2 min to rebuild from cache. Entities land
just under the 45–65 target (the corpus really has 43 distinct nodes); the raw
edge count is above 140–200 because edges are keyed on `source_chunk_id` for
provenance (distinct `(src,type,tgt)` ≈ 130).

### 1.5 Extraction eval ⬜

`scripts/eval_extraction.py`, `EXTRACTION_METRICS.md`.

---

## Phase 2 — Vector index

### 2.1 Embed + store ✅

Goal: every chunk embedded locally and stored in pgvector, keyed on `chunk_id`,
with metadata linking it back to the graph.

| File | What it does |
|------|--------------|
| `src/ingest/load_vector.py` | `vector_store()` — the one `PGVector` handle (collection `meridian_chunks`, cosine, 384-dim, `use_jsonb`, exact scan — no HNSW). `entity_ids_by_chunk(results)` — `chunk_id → sorted resolved entity ids` (each raw entity run through `resolve_entity`, grouped by `source_chunk_id`, so the list is complete even for entities the graph merge re-attributed elsewhere). `load_vector(chunks, results)` — build one `Document` per chunk (`page_content` = chunk text, metadata `{chunk_id, document, entity_ids}`) and `add_documents(..., ids=[chunk_id])` so a re-run upserts, never duplicates. `--wipe` drops + recreates the collection. Embeddings are local (`bge-small`) → **no API call**. |
| `scripts/ingest_corpus.py` | now also calls `load_vector(chunks, results, wipe_first=…)` after the graph load and prints `vectors: N chunks embedded`. |
| `tests/test_load_vector.py` | 4 unit tests (entity-id grouping/resolution, document metadata shaping) + 2 `@pytest.mark.pgvector` gate tests (real embed + upsert idempotency, similarity search returns the right chunk, 384-dim). |

**Concept:** vector search covers **all 42 chunks** even though the graph only
has 39 — the 3 deferred chunks are embedded with `entity_ids: []`. The vector
store and graph share `chunk_id` as the join key for hybrid retrieval (Phase 3).
`entity_ids` is computed from the *raw* per-chunk extractions, not the merged
entities, so it lists every node a chunk mentions.

### 2.2 Recall sanity check ✅

Goal: confirm vector retrieval actually surfaces the right chunk before the
pipeline depends on it.

| File | What it does |
|------|--------------|
| `tests/fixtures/vector_eval.json` | 12 `(question → gold_chunk_id)` pairs — definitional questions whose answer lives in exactly one chunk; 8 are lifted from `data/benchmark/questions.md` (the VECTOR-route B01–B08), 4 are extra. Carries the gate (`recall_at_5_gate: 0.9`) and `k`. |
| `scripts/eval_vector.py` | Builds the corpus into a **scratch** collection `meridian_eval` (chunks only — no LLM, no graph), runs each question through `similarity_search`, prints recall@1/3/5 and per-question rank, drops the scratch collection. `PASS` if recall@5 ≥ gate. Also holds the "why no ANN index" write-up (module docstring). |
| `scripts/__init__.py` | makes `scripts/` importable so tests reuse `eval_vector` logic. |
| `src/ingest/load_vector.py` | `vector_store(collection=…)` gained a param so the eval never touches the real `meridian_chunks`. |
| `tests/test_vector_recall.py` | 1 unit test (every fixture gold id is a real chunk — guards against drift) + 1 `@pytest.mark.pgvector` gate test (recall@5 ≥ 0.9). |

**Result:** **recall@1 = 1.00** over all 12 questions. Expected — with ~42
distinct-topic vectors and an *exact* scan, the nearest chunk is the right chunk.
This is the evidence that an ANN index would be pure downside here.

## Phase 3 — Routing & retrieval

### 3.1 Router ✅

Goal: classify each question into the retrieval strategy that answers it best,
before any retrieval runs.

| File | What it does |
|------|--------------|
| `src/pipeline/__init__.py` | package marker for the query pipeline. |
| `src/pipeline/router.py` | `route_question(question)` — one `router_model.with_structured_output(RoutingDecision)` call (`gpt-oss-20b`, small/fast) with a few-shot system prompt (12 examples: 4 VECTOR / 4 GRAPH / 4 REFUSE, 10 lifted from the benchmark), then `_apply_confidence_floor`: a non-HYBRID route with `confidence < 0.70` is downgraded to HYBRID (rules.md §5.1 — "unsure? run both"). Logs `question → route conf` for every call (Phase 5 reads it). No DB, no Cypher. |
| `tests/fixtures/routing_eval.json` | 21 hand-labelled questions, **disjoint from the few-shot block** (a test enforces this). VECTOR/GRAPH gold tracks the benchmark; REFUSE items are fresh. `accuracy_gate: 0.90`. |
| `scripts/eval_router.py` | Runs the eval set through `route_question`, prints per-question hits + accuracy, writes `ROUTING_METRICS.md` (accuracy + gold×predicted confusion matrix + misclassification list). Reusable `load_eval_set` / `run_eval` imported by the test. |
| `tests/test_router.py` | 8 unit tests (confidence-floor cases with a stub model, fixture-hygiene / no-leakage guard) + 1 `@pytest.mark.llm` gate test (accuracy ≥ 0.90). |
| `ROUTING_METRICS.md` | generated. |

**Result:** **95.2%** (20/21). GRAPH and REFUSE are clean; the one miss is
*"What does the Billing Service depend on?"* → VECTOR (borderline — the answer is
in one doc, but the benchmark wants the DEPENDS_ON traversal). Comfortably over
the 90% gate.

**Concept:** the router never sees the corpus or the graph — it reasons purely
about the *shape* of the question. HYBRID is deliberately rare from the model
itself; most HYBRIDs will come from the confidence floor at runtime.

### 3.2 Graph retriever ✅

Goal: answer a GRAPH-routed question from Neo4j with cited sentences, and never
let the model touch Cypher.

| File | What it does |
|------|--------------|
| `src/graph/queries.py` (read templates) | 7 generic read templates — the retriever's entire Cypher surface. `RESOLVE_ENTITY` / `RESOLVE_ENTITY_FUZZY` (canonical name + alias, then substring), `NEIGHBORS` / `COUNT_NEIGHBORS` (1-hop with `$rel` / `$direction` / `$neighbor_type` filters, all nullable), `TWO_CONSTRAINT` (node satisfying two edges), `PATH_BETWEEN` (`shortestPath ≤5`), `BLAST_RADIUS` (CVE → library → `DEPENDS_ON*1..3` service → product). The rel type is always a `WHERE type(r) = $rel` **parameter**, never interpolated — one template per shape, not per type. |
| `src/models/answer.py` (`GraphFact`) | One relationship rendered as a sentence + its `source_chunk_id` + `evidence`. The graph-side counterpart to `Passage`; synthesis cites it identically. |
| `src/pipeline/retrieve_graph.py` | `retrieve_graph(question)` — **exactly one LLM call** fills a `GraphQueryPlan` (`intent`, `anchors`, `relationship`, `direction`, …) via `router_model.with_structured_output`; the model is told it does **not** write Cypher. Then deterministic: resolve each anchor mention to a node id (concern vocab → canonical/alias → fuzzy), pick the template for `plan.intent`, run it via `Neo4jGraph.query` with named params, turn each row into a sentence with a per-relationship-type verb (`_REL_VERB` / `_REL_VERB_PLURAL`). Unresolved anchor or empty result → empty `GraphRetrieval` (not an error) so the pipeline falls back to vector. Times the Cypher only (the plan call is excluded from the latency gate). |
| `scripts/eval_graph_retrieval.py` + `tests/fixtures/graph_eval.json` | Gate runner over B09/B14/B16/B17/B24. `gold_nodes` (recall 1.0), `exact` (result must equal gold), `extra_ok` (nodes the built corpus legitimately adds), `expected_count` (the count sentence leads correctly). |
| `tests/test_retrieve_graph.py` | 8 unit (pure formatting + stub-plan/fake-client wiring) + 2 `@pytest.mark.neo4j` (real resolve, ≤200 ms neighbours) + 1 `@pytest.mark.llm+neo4j` **gate**. |

**Result:** gate **PASS** — 5/5 exact, all queries 12–56 ms (budget 200). One
data nuance surfaced: the 5 `USES PostgreSQL` edges' first `source_chunk_id` is
`vulnerabilities/cve-2024-0985-postgresql.md` (that doc enumerates the affected
services) rather than a service doc — a weak-but-valid citation, a Phase 1.5 /
Phase 4 concern, not a retrieval bug.

**Concept:** the LLM decides *what to ask*; the code decides *how to ask it*.
That split is the whole security argument against `GraphCypherQAChain` and what
makes results reproducible.

### 3.3 Vector retriever ✅

Goal: top-k corpus passages for a VECTOR-routed question.

| File | What it does |
|------|--------------|
| `src/pipeline/retrieve_vector.py` | `retrieve_vector(question, k=5)` — one `PGVector.similarity_search_with_score` against `meridian_chunks` (exact cosine, no HNSW). Each hit → `Passage(chunk_id, document, content, score)`; `score` keeps PGVector's raw cosine *distance* (0 = identical, rows already sorted ascending). No LLM call — embeddings are local. Empty result → `[]` (pipeline routes to REFUSE). `store` is injectable for tests. |
| `scripts/eval_vector_retrieval.py` + `tests/fixtures/vector_retrieval_eval.json` | Gate over B01–B08. `gold_chunks` lists every chunk that legitimately answers (a split doc contributes several; some questions are answerable from either of two docs); pass = a gold chunk in the top `rank_within` (3). |
| `tests/test_retrieve_vector.py` | 5 unit (fake store — passage mapping, k pass-through, empty, metadata fallback) + 1 fixture-hygiene + 1 `@pytest.mark.pgvector` **gate**. |

**Result:** gate **PASS** — B01–B08 all **rank 1**.

### 3.4 Merge + LangGraph wiring ✅

Goal: combine the two retrieval sides and wire route → retrieve → merge as a
`StateGraph` with fallbacks.

| File | What it does |
|------|--------------|
| `src/models/answer.py` (`MergedContext`) | `{graph_facts, passages, chunk_ids}`. `chunk_ids` is the *retrieved set* the Phase 4.2 citation validator checks against. `is_empty()`. |
| `src/pipeline/merge.py` | `merge(graph_facts, passages)` — dedupe passages to best-scoring per `chunk_id` then drop near-duplicate bodies (`SequenceMatcher ≥ 0.95`), dedupe exact-repeat graph facts, union the sources (graph first). `labelled_context()` renders `GRAPH FACTS` / `RETRIEVED PASSAGES` headers with a `[chunk_id]` tag on every line (rules.md §5.7). No LLM call. |
| `src/pipeline/graph.py` | `compile_pipeline(router, graph_fn, vector_fn)` → compiled `StateGraph`. Nodes `route / retrieve_graph / retrieve_vector / merge / refuse`, each a plain `(state) -> partial state`. Conditional edges: route → {graph, vector, refuse}; after graph → vector if **HYBRID or graph empty**, else merge; after vector → merge if anything retrieved, else refuse. `run_pipeline(question)` uses a module-level compiled singleton. The three retrieval callables are injected so tests use fakes. |
| `tests/test_merge.py` (7) · `tests/test_pipeline.py` (7) | merge dedupe/union/labelling; every route + both fallbacks (graph-empty→vector, all-empty→REFUSE), HYBRID runs both. |

**Concept:** the pipeline is deliberately linear even for HYBRID (graph *then*
vector, not parallel) — simpler to reason about and to test, and retrieval is
fast enough that fan-in buys nothing at this scale.

**End-to-end smoke:** all four routes behave — `What is the Auth Service?` →
VECTOR (5 passages), `Which services use PostgreSQL?` → GRAPH (5 facts),
`If Log4Shell is exploited…` → GRAPH blast-radius (2 products), `Should the
Payments Team rewrite…` → REFUSE (nothing retrieved).

## Phase 4 — Synthesis & API

### 4.1 Synthesize ✅

Goal: turn the merged context into a concise answer where every claim is cited.

| File | What it does |
|------|--------------|
| `src/pipeline/synthesize.py` | `synthesize(question, context, routing_used)` — one `chat_model.with_structured_output(SynthesisResult)` call (`gpt-oss-120b`). The context goes in under `GRAPH FACTS` / `RETRIEVED PASSAGES` headers (`merge.labelled_context`), each line/passage tagged `[chunk_id]`; the prompt requires a `Citation{claim, chunk_id, source_type}` per claim, `chunk_id` copied verbatim from a bracket. Empty context → a fixed "not enough information" answer, no LLM call. `allowed_chunk_ids` adds a `Cite ONLY from: […]` line (the validator's retry uses it). Assembles the `GroundedAnswer` (`graph_paths` = fact sentences, `vector_passages` = chunk ids, `latency_ms` = the call). |
| `src/models/answer.py` (`SynthesisResult` lives in `synthesize.py`; `GroundedAnswer` gained `notes`) | `notes` carries validator actions through to the API response. |
| `scripts/eval_synthesis.py` + `tests/fixtures/synthesis_eval.json` | 5 questions (VECTOR / GRAPH-neighbors / GRAPH-count / blast-radius / composition). Gate = non-empty answer, ≥1 citation, every `citation.chunk_id` in the retrieved set, every `must_mention` string present. |
| `tests/test_synthesize.py` | 3 unit (stub model — assembly, empty-context short-circuit, multi-citation) + 1 `llm+neo4j+pgvector` **gate**. |

**Result:** gate **PASS** — 5/5 coherent + fully cited. Fixed while building:
the `count` intent's tally sentence had no `source_chunk_id` (rendered a fake
`[graph]` tag the model then cited) — `_count_sentence` now inherits the first
member edge's chunk id.

### 4.2 Validate citations ✅

Goal: guarantee every cited chunk id is one that retrieval actually returned.

| File | What it does |
|------|--------------|
| `src/pipeline/validate.py` | `validate_answer(answer, context, question)` — if every `citation.chunk_id ∈ context.chunk_ids`, return unchanged. Otherwise regenerate **once** with `allowed_chunk_ids=retrieved`, keep only the citations that are now valid, and append a note listing what was dropped. |
| `src/pipeline/graph.py` (`compile_answer_pipeline`, `answer_question`) | Wraps the Phase 3.4 retrieval graph as a subgraph, then `synthesize` → `validate` nodes; a REFUSE route skips straight to `END` (no synthesis). `validate` folds the pipeline's `notes` (e.g. the graph→vector fallback note) into `answer.notes`. `answer_question(q)` is the singleton entry point. |
| `scripts/eval_validation.py` | (1) 100% citation validity over the synthesis sample via the full `answer_question`; (2) a fabricated citation spliced into a real answer is removed by `validate_answer`. |
| `tests/test_validate.py` | 3 unit (`validate_answer` pass-through / regenerate-and-filter / still-bad-note) + 4 pipeline-wiring (synthesize→validate order, REFUSE skips synthesis, fallback note reaches the answer) + 1 `llm+neo4j+pgvector` **gate**. |

**Result:** gate **PASS** — 6/6 (5 valid + injection caught).

### 4.3 API + end to end ✅

Goal: one HTTP entry point, correct status per route, honest latency.

| File | What it does |
|------|--------------|
| `src/api/schemas.py` | `QueryRequest{question ≤1000 chars, top_k, max_hops}` (the last two accepted for forward-compat; pipeline uses its own defaults), `OutOfScope` (422 body), `ErrorBody` (400/503), `HealthResponse`. |
| `src/api/dependencies.py` | `datastore_status()` pings Neo4j (`RETURN 1`) + Postgres (`SELECT 1`) and never raises; `require_datastores()` is the `/query` dependency that turns a down store into `GraphUnavailableError` → 503. |
| `src/api/main.py` | `POST /query` → `answer_question`; REFUSE → 422 `{error:"out_of_scope", reason, message}`, blank/oversized body → 400 (a `RequestValidationError` handler reshapes FastAPI's default 422), `ApplicationError` → 503/500. `GET /health` → 200 with per-store status (`degraded` if one is down). The app builds no provider clients. |
| `scripts/eval_api.py` → `API_METRICS.md` | Drives `TestClient` once per route (VECTOR/GRAPH/HYBRID/REFUSE), checks status + VECTOR-citation validity, writes the latency table. |
| `tests/test_api.py` | 8 unit (stubbed `answer_question`, overridden dependency — answer shape, 422/400/503, health ok/degraded) + 1 `llm+neo4j+pgvector` **gate**. |

**Result:** gate **PASS** — 4/4 routes correct. **Latency caveat:** the cold gate
run showed 7 s–127 s because every LLM call was a cache miss against Groq's free
tier (rate-limit back-off) with one Gemini fallback; `API_METRICS.md` is
regenerated warm (all LLM calls cache hits) so the number reflects Cypher +
local embedding + merge/validate overhead, not API round-trips.

## Phase 5 — Benchmark & writeup ⬜

`src/baselines/vector_only.py`, `scripts/benchmark.py`, `BENCHMARK_RESULTS.md`,
`FINDINGS.md`, `SETUP.md`.
