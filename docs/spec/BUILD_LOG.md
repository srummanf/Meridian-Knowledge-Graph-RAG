# Build log

A file-by-file map of **what each file is and why it exists**, grouped by build
step. The spec is in [`prd.md`](./prd.md), [`architecture.md`](./architecture.md),
[`rules.md`](./rules.md), [`PLAN.md`](./PLAN.md); this file is the "what am I
looking at" index.

Legend: ✅ done · ⬜ not started.

---

## Getting started ✅

Both databases running, both LLM providers reachable, config in one place.

| File | What it does |
|------|--------------|
| `pyproject.toml` | Package + dependency list. Installed with `pip install -e ".[dev]"`. |
| `docker-compose.yml` | Neo4j 5 (`7474`/`7687`) and Postgres 16 + pgvector (host `5433` → container `5432`) with health checks and named volumes. |
| `.env.example` | Template for `.env`: DB DSNs, the two API keys, model IDs. |
| `src/config.py` | **The only file that builds provider classes.** `Settings` (from `.env`), the `chat_model()` / `router_model()` / `extract_model()` / `embeddings()` factories with Groq→Google fallback, and the SQLite LLM cache. |
| `src/logging_config.py` | One stdout handler, consistent format, quiets noisy libraries. |
| `scripts/check_setup.py` | The setup gate: pings Neo4j, Postgres (+ the `vector` extension), local embeddings (384-dim), and both LLM providers. Prints PASS/FAIL. |

**Concept:** every I/O boundary (databases, LLMs, embeddings) is wrapped once, so
the rest of the code never imports a provider SDK directly.

---

## Step 1 — Data ingestion

### 1.1 Models ✅

Typed, validated shapes for everything that flows through the pipeline.

| File | What it does |
|------|--------------|
| `src/models/domain.py` | The graph vocabulary. `EntityType` (11), `RelationType` (12), `DataConcern` (5, for `HANDLES`). `Entity` / `Relationship` with `confidence ∈ [0,1]`. `slugify()` + `make_entity_id()` build deterministic IDs (`service:auth-service`). `RELATION_PROPERTY_KEYS`, `CONFIDENCE_FLOOR = 0.80`. |
| `src/models/extraction.py` | `ExtractionResult = {entities, relationships}` — the schema handed to `with_structured_output`. |
| `src/models/routing.py` | `RoutingDecision = {route, confidence, reasoning, entities_detected}`, `route ∈ {VECTOR, GRAPH, HYBRID, REFUSE}`, `HYBRID_CONFIDENCE_FLOOR = 0.70`. |
| `src/models/answer.py` | `Passage`, `GraphFact`, `MergedContext`, `Citation`, `GroundedAnswer`, `SynthesisResult`. |
| `src/models/__init__.py` | Flat re-exports (`from src.models import Entity`). |
| `src/utils/errors.py` | One exception hierarchy (`ApplicationError` base, `ExtractionError`, `LLMUnavailableError`, `GraphUnavailableError`, `RetrievalError`). The API maps these to HTTP codes. |
| `tests/test_models.py` | Models accept valid data, reject unknown enums and out-of-range confidence. |

**Concept:** `source_chunk_id` defaults to `""` — the LLM never sets it; the
ingest pipeline stamps it. Every fact in the graph must trace back to a chunk.

### 1.2 Chunking ✅

| File | What it does |
|------|--------------|
| `src/ingest/chunk.py` | `Chunk` model + `chunk_corpus()` — walks `data/**/*.md` (skips `ONTOLOGY`/`SCHEMA`/`README`/`benchmark`). One chunk per doc; a doc over ~280 estimated tokens is split on `##` and its sections packed into ~250-token sub-chunks. IDs: `services/auth-service.md` or `services/billing-service.md#overview`. Produces **42 chunks**. |
| `tests/test_chunk.py` | 37 docs → 40–55 chunks, unique IDs, non-empty content, split docs cover all their sections. |

**Concept:** whole-doc chunks by default, because each doc describes exactly one
entity — that keeps extraction evidence and citations clean. Splitting is the
exception for the few long service docs.

### 1.3 Extraction ✅

| File | What it does |
|------|--------------|
| `src/ingest/extract.py` | `extract_chunk(chunk)` — system prompt from `data/ONTOLOGY.md` + the `SCHEMA.md` example, `chat_model.with_structured_output(ExtractionResult)`, drop rows below confidence 0.80, then `_validate()` (evidence is a real substring, allowed properties, endpoints exist). Retry ≤3 with the errors fed back, then raise `ExtractionError`. `extract_corpus()` collects failures instead of aborting. `_stamp()` writes `source_chunk_id`. Distinguishes a Groq `413` (request too large) from real throttling and switches that chunk to Google-only. |
| `tests/test_extract.py` | Unit tests (stub model) for validation + retry; `@pytest.mark.llm` gate tests: clean extraction on three service docs + a cache-hit check. |

**Concept:** the LLM never touches the database and its output is never trusted
raw — every field is validated, and `evidence` must be a real substring of the
chunk so citations cannot be hallucinated. Groq's `gpt-oss` needs
`with_structured_output(..., method="json_schema")`.

### 1.4 Resolution and graph load ✅ — 42/42 chunks live

| File | What it does |
|------|--------------|
| `src/ingest/resolve.py` | `resolve(results)` → `(entities, relationships)`. Per entity: strip a leading article, peel a trailing version into `properties.version`, apply the `data/ONTOLOGY.md` alias table (a hit replaces name **and** type), recompute the deterministic id, merge entities that now share an id. Per relationship: re-point endpoints at resolved entities, map `HANDLES` targets to `concern:<slug>`, drop self-loops, store `ALTERNATIVE_TO` one direction, merge edges sharing `(source, type, target, source_chunk_id)`. Pure and deterministic. |
| `src/graph/queries.py` | **Every Cypher string.** `SCHEMA_STATEMENTS`, `WIPE`, 11 `ENTITY_TEMPLATES` and 12 `RELATIONSHIP_TEMPLATES` (built from the enums — the only place a type name is formatted into a string; keyed on `source_chunk_id`; `HANDLES` targets a `:Concern` node), count queries, and the 7 read templates for the retriever (see 2.2). |
| `src/graph/client.py` | `graph_client()` — the shared `Neo4jGraph` (one driver per process). `ensure_schema()`, `wipe()`. |
| `src/ingest/load_graph.py` | `load_graph(entities, relationships)` — `MERGE` each entity (its `properties` map is JSON-serialised because Neo4j properties must be primitive), then each relationship via its template. Returns live DB counts. |
| `scripts/ingest_corpus.py` | `chunk_corpus() → extract_corpus() → resolve() → load_graph() → load_vector()`. `--wipe` for a clean rebuild. Prints the summary + type breakdowns; pauses cleanly (exit 2) if a chunk finds both providers rate-limited. |
| `tests/test_resolve.py` · `tests/test_load_graph.py` (3 `@pytest.mark.neo4j`). Cypher-template checks live in `tests/test_retrieve_graph.py`. |

**Concept:** resolution is where "the gateway", "api-gw", and "edge gateway" all
become the one node `service:api-gateway`. Determinism + `MERGE`-on-deterministic-id
is what makes re-ingesting a no-op.

**Free-tier history.** Groq's free tier rejects any single request over ~8000
tokens/minute; about eight larger chunks exceed that and route to Gemini. A day
of iterative debugging burned both daily quotas and left three chunks parked;
their cached extractions were later recovered (two cache-hit cleanly, and a
one-off dropped one malformed relationship from the third's cached response). The
full corpus is now in the graph — **42 chunks, 43 entities / 222 relationships**,
idempotent, $0, ~2 minutes to rebuild from cache. Entities land just under the
planned 45–65 (43 distinct nodes); edges run above 140–200 because they are keyed
on `source_chunk_id` for provenance (distinct `(src, type, tgt)` triples ≈ 130).

### 1.5 Vector index and recall check ✅

| File | What it does |
|------|--------------|
| `src/ingest/load_vector.py` | `vector_store()` — the one `PGVector` handle (collection `meridian_chunks`, cosine, 384-dim, exact scan, no HNSW). `entity_ids_by_chunk()` — `chunk_id → sorted resolved entity ids` computed from the raw per-chunk extractions. `load_vector()` — one `Document` per chunk (metadata `{chunk_id, document, entity_ids}`), `add_documents(..., ids=[chunk_id])` so a re-run upserts. Embeddings are local (`bge-small`) — no API call. |
| `tests/fixtures/vector_eval.json` | 12 `(question → gold_chunk_id)` pairs; 8 lifted from `data/benchmark/questions.md` (VECTOR-route B01–B08), 4 extra. Carries `recall_at_5_gate: 0.9`. |
| `tests/test_load_vector.py` | Unit tests (entity-id grouping, document shaping) + `@pytest.mark.pgvector` gate (real embed + upsert idempotency, similarity search returns the right chunk). |
| `tests/test_retrieve_vector.py` (recall half) | `test_recall_fixture_gold_ids_are_real_chunks` (drift guard, offline) + `test_recall_at_5_clears_the_gate` (`@pytest.mark.pgvector` — recall@5 over the fixture against the live collection). |

**Concept:** the vector store and the graph share `chunk_id` as the join key for
hybrid retrieval. **recall@1 = 1.00** over all 12 questions — with ~42
distinct-topic vectors and an exact scan, the nearest chunk is the right chunk,
which is the evidence that an ANN index would be pure downside.

### 1.6 Extraction eval ⬜

Planned: `scripts/eval_extraction.py`, an `EXTRACTION_METRICS.md`. Would catch the
citation-attribution bug in 2.2. On the roadmap.

---

## Step 2 — RAG pipeline

### 2.1 Router ✅

Classify each question into the retrieval strategy that answers it best, before
any retrieval runs.

| File | What it does |
|------|--------------|
| `src/pipeline/__init__.py` | package marker. |
| `src/pipeline/router.py` | `route_question(question)` — one `router_model.with_structured_output(RoutingDecision)` call (`gpt-oss-20b`) with a 12-example few-shot prompt, then `_apply_confidence_floor`: a non-HYBRID route with `confidence < 0.70` is downgraded to HYBRID ([`rules.md`](./rules.md) §5.1 — "unsure? run both"). Logs `question → route conf` for every call. No DB, no Cypher. |
| `tests/fixtures/routing_eval.json` | 21 hand-labelled questions, **disjoint from the few-shot block** (a test enforces this). `accuracy_gate: 0.90`. |
| `tests/test_router.py` | Confidence-floor unit tests + a fixture-hygiene / no-leakage guard + the `@pytest.mark.llm` accuracy gate. |
| [`../results/ROUTING_METRICS.md`](../results/ROUTING_METRICS.md) | Committed snapshot of one run's accuracy + confusion matrix. |

**Result: 95.2% (20/21).** GRAPH and REFUSE are clean; the one miss is *"What
does the Billing Service depend on?"* → VECTOR (borderline — the answer is in one
doc, but the intent is a `DEPENDS_ON` traversal).

**Concept:** the router never sees the corpus or the graph — it reasons purely
about the *shape* of the question.

### 2.2 Graph retriever ✅

Answer a GRAPH-routed question from Neo4j with cited sentences, and never let the
model touch Cypher.

| File | What it does |
|------|--------------|
| `src/graph/queries.py` (read templates) | 7 generic read templates — the retriever's entire Cypher surface. `RESOLVE_ENTITY` / `RESOLVE_ENTITY_FUZZY`, `NEIGHBORS` / `COUNT_NEIGHBORS` (1-hop with nullable `$rel` / `$direction` / `$neighbor_type` filters), `TWO_CONSTRAINT`, `PATH_BETWEEN` (`shortestPath ≤5`), `BLAST_RADIUS` (CVE → library → `DEPENDS_ON*1..3` service → product). The relationship type is always a `WHERE type(r) = $rel` **parameter** — one template per shape, not per type. |
| `src/models/answer.py` (`GraphFact`) | One relationship rendered as a sentence + its `source_chunk_id` + `evidence`. Synthesis cites it like a `Passage`. |
| `src/pipeline/retrieve_graph.py` | `retrieve_graph(question)` — **exactly one LLM call** fills a `GraphQueryPlan` (`intent`, `anchors`, `relationship`, `direction`, …); the model is told it does **not** write Cypher. Then deterministic: resolve each anchor to a node id (concern vocab → canonical/alias → fuzzy), pick the template for `plan.intent`, run it via `Neo4jGraph.query` with named params, render each row with a per-relationship-type verb. Unresolved anchor or empty result → empty `GraphRetrieval` (not an error) so the pipeline falls back to vector. Times the Cypher only. |
| `tests/fixtures/graph_eval.json` | Gate set B09/B14/B16/B17/B24: `gold_nodes` (recall 1.0), `exact`, `extra_ok`, `expected_count`. |
| `tests/test_retrieve_graph.py` | Pure formatting + Cypher-template checks + stub-plan/fake-client wiring + `@pytest.mark.neo4j` (real resolve, ≤200 ms) + the `llm + neo4j` **gate**. |

**Result: gate PASS** — 5/5 exact, all queries 12–56 ms (budget 200). One data
nuance: the five `USES PostgreSQL` edges' first `source_chunk_id` is
`vulnerabilities/cve-2024-0985-postgresql.md` (that doc enumerates the affected
services) rather than a service doc — a weak-but-valid citation, fixable by an
extraction eval, not a retrieval bug.

**Concept:** the LLM decides *what to ask*; the code decides *how to ask it*.
That split is the whole security argument against `GraphCypherQAChain`.

### 2.3 Vector retriever ✅

| File | What it does |
|------|--------------|
| `src/pipeline/retrieve_vector.py` | `retrieve_vector(question, k=5)` — one `PGVector.similarity_search_with_score` against `meridian_chunks` (exact cosine). Each hit → `Passage(chunk_id, document, content, score)`; `score` is the raw cosine distance. No LLM call. Empty result → `[]` (pipeline routes to REFUSE). `store` is injectable for tests. |
| `tests/fixtures/vector_retrieval_eval.json` | Gate over B01–B08: pass = a gold chunk in the top `rank_within` (3). |

**Result: gate PASS** — B01–B08 all rank 1.

### 2.4 Merge and LangGraph wiring ✅

| File | What it does |
|------|--------------|
| `src/models/answer.py` (`MergedContext`) | `{graph_facts, passages, chunk_ids}`. `chunk_ids` is the *retrieved set* the citation validator checks against. `is_empty()`. |
| `src/pipeline/merge.py` | `merge(graph_facts, passages)` — dedupe passages to best-scoring per `chunk_id` then drop near-duplicate bodies (`SequenceMatcher ≥ 0.95`), dedupe repeat facts, union the sources (graph first). `labelled_context()` renders `GRAPH FACTS` / `RETRIEVED PASSAGES` headers with a `[chunk_id]` tag on every line. No LLM call. |
| `src/pipeline/graph.py` | `compile_pipeline(router, graph_fn, vector_fn)` → compiled `StateGraph`. Nodes `route / retrieve_graph / retrieve_vector / merge / refuse`, each a plain `(state) → partial state`. Conditional edges do the routing and the fallbacks (graph empty or HYBRID → vector; nothing retrieved → REFUSE). `run_pipeline(q)` is the retrieval-only singleton. Retrieval callables are injected so tests use fakes. |
| `tests/test_merge.py` · `tests/test_pipeline.py` | merge dedupe/union/labelling; every route + both fallbacks; HYBRID runs both. |

**Concept:** the pipeline is deliberately linear even for HYBRID (graph *then*
vector, not parallel) — simpler to reason about and to test, and retrieval is
fast enough that fan-in buys nothing at this scale.

### 2.5 Synthesis ✅

| File | What it does |
|------|--------------|
| `src/pipeline/synthesize.py` | `synthesize(question, context, routing_used)` — one `chat_model.with_structured_output(SynthesisResult)` call (`gpt-oss-120b`) over the labelled context; a `Citation{claim, chunk_id, source_type}` per claim, `chunk_id` copied verbatim from a `[bracket]`. Empty context → a fixed "not enough information", no LLM call. `allowed_chunk_ids` adds a `Cite ONLY from: […]` line (the validator's retry uses it). Assembles the `GroundedAnswer`. |
| `tests/fixtures/synthesis_eval.json` | 5 questions (VECTOR / GRAPH-neighbors / GRAPH-count / blast-radius / composition). Gate = non-empty answer, ≥1 citation, every `citation.chunk_id` in the retrieved set, every `must_mention` string present. |
| `tests/test_synthesize.py` | Unit (stub model — assembly, empty-context short-circuit, multi-citation) + the `llm + neo4j + pgvector` gate. |

**Result: gate PASS** — 5/5 coherent + fully cited. Fixed while building: the
`count` intent's tally sentence had no `source_chunk_id`; `_count_sentence` now
inherits the first member edge's chunk id.

### 2.6 Citation validation ✅

| File | What it does |
|------|--------------|
| `src/pipeline/validate.py` | `validate_answer(answer, context, question)` — if every `citation.chunk_id ∈ context.chunk_ids`, return unchanged. Otherwise regenerate **once** with `allowed_chunk_ids=retrieved`, keep only the valid citations, append a note listing what was dropped. |
| `src/pipeline/graph.py` (`compile_answer_pipeline`, `answer_question`) | Wraps the retrieval graph as a subgraph, then `synthesize` → `validate` nodes; a REFUSE route skips straight to `END`. `validate` folds the pipeline's `notes` into `answer.notes`. `answer_question(q)` is the full-pipeline singleton. |
| `tests/test_validate.py` | Unit (`validate_answer` pass-through / regenerate-and-filter / still-bad-note) + pipeline wiring (synthesize→validate order, REFUSE skips synthesis, fallback note reaches the answer) + the `llm + neo4j + pgvector` gate: 100% citation validity over the sample + an injected fake citation is caught. |

**Result: gate PASS.**

---

## Step 3 — API ✅

One HTTP entry point, correct status per route, honest latency.

| File | What it does |
|------|--------------|
| `src/api/schemas.py` | `QueryRequest{question ≤1000 chars, top_k, max_hops}` (the last two are accepted for forward compatibility), `OutOfScope` (422 body), `ErrorBody` (400/503), `HealthResponse`. |
| `src/api/dependencies.py` | `datastore_status()` pings Neo4j (`RETURN 1`) and Postgres (`SELECT 1`) and never raises; `require_datastores()` is the `/query` dependency that turns a down store into a 503. |
| `src/api/main.py` | `POST /query` → `answer_question`; REFUSE → 422 `{error:"out_of_scope", reason, message}`, blank/oversized body → 400 (a `RequestValidationError` handler reshapes FastAPI's default 422), `ApplicationError` → 503/500. `GET /health` → 200 with per-store status. The app builds no provider clients. |
| `scripts/ask.py` | CLI wrapper: `python scripts/ask.py "question"` runs `answer_question` and prints the grounded answer (`--json` for the raw body). |
| `tests/test_api.py` | Unit (stubbed `answer_question`, overridden dependency — answer shape, 422/400/503, health ok/degraded) + the `llm + neo4j + pgvector` gate: one real request per route. |

**Result: gate PASS** — 4/4 routes correct.
[`../results/API_METRICS.md`](../results/API_METRICS.md) is a committed snapshot
of one warm run's latency table.

---

## Step 4 — Testing ✅

One test module per source module under `tests/`, plus `tests/fixtures/*.json`
for the labelled question sets. Markers gate the tests that need external
services:

| Marker | Needs | Notes |
|--------|-------|-------|
| _(none)_ | nothing | 237 tests, ~20 s |
| `llm` | Groq / Google keys | calls are cached after the first run |
| `neo4j` | Neo4j + loaded corpus | `test_load_graph.py` **wipes and rebuilds** the graph |
| `pgvector` | Postgres + loaded corpus | `test_load_vector.py` **rebuilds** the `meridian_chunks` collection |

After running the full marked suite, re-run `python scripts/ingest_corpus.py
--wipe` to restore the indexes.

---

## Step 5 — Benchmark and findings

### 5.1 Baseline and harness ✅

| File | What it does |
|------|--------------|
| `src/baselines/vector_only.py` | `answer_vector_only(q)` — `compile_answer_pipeline(router=_force_vector)`: the router is pinned to `VECTOR`, so the graph node never runs. Same chunks, same embeddings, same synthesis prompt, same citation validator — the graph is the only variable. |
| `scripts/benchmark.py` | Parses `data/benchmark/questions.md` into `tests/fixtures/benchmark_questions.json` (id, question, category, gold route/answer/sources). Runs each question through `answer_question` and `answer_vector_only`, recording route, answer, cited chunk ids, notes, latency, and a chars/4 token estimate. Writes `tests/fixtures/benchmark_run.json` **after every call** so a kill mid-run resumes cleanly (`--only`, `--parse-only`, `--questions B17,B24`). Emits the grading skeleton, then leaves it alone once it carries scores. |
| `scripts/score_benchmark.py` | Reads the `G`/`V` scores back from the results doc, computes mean accuracy per category per system, checks the gate (1-hop parity ±0.05; 2-hop Δ ≥ +0.15; 3-hop Δ ≥ +0.30; aggregation graph ≥ 0.80 & vector ≤ 0.20). |
| `tests/test_benchmark.py` | Parser (the 14-question scoped set) + scorer (score parsing, category means, gate checks) — all offline. |

**Concept:** the benchmark isolates one variable. Both systems share everything
except routing, so a category-level accuracy gap is attributable to graph
traversal, not a better prompt or better chunks.

### 5.2 Grade and analyse ✅ — gate NOT met; that is the finding

The set was cut from 30 to **14** — what one $0 free-tier run completes. Graded
per category (graph / vector): 1-hop 0.84 / 0.84 (parity), 2-hop 1.00 / 1.00,
3-hop 0.75 / 0.75, aggregation 1.00 / 1.00, refusal 1.00 / 1.00 — **Δ ≈ 0.00
everywhere.** Two structural causes: the corpus pre-aggregates its relationships
(hub docs list their consumers and state counts), so vector answers nominal
multi-hop from a single document; and one true 3-hop question (B18) fits none of
the six query-plan shapes. Full analysis in
[`../results/FINDINGS.md`](../results/FINDINGS.md).

### 5.3 Writeup ✅

[`../results/FINDINGS.md`](../results/FINDINGS.md) (corpus pre-aggregation, the
template ceiling, where the graph wins and loses, cost and latency honesty, why
`GraphCypherQAChain` is not used, "when to reach for a graph") ·
[`../SETUP.md`](../SETUP.md) · the README benchmark table.
