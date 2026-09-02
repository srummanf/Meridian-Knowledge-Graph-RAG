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

### 1.4 Graph load + resolution 🚧 (39/42 chunks live; 3 deferred to a top-up run)

Goal: resolve the per-chunk extractions into one clean graph and MERGE it into Neo4j.

| File | What it does |
|------|--------------|
| `src/ingest/resolve.py` | `resolve(results)` → `(entities, relationships)`. Per entity: strip a leading article, peel a trailing version into `properties.version`, look up the `ONTOLOGY.md` §3 alias table (a hit replaces name **and** type), recompute the deterministic id, then merge entities that now share an id. Per relationship: re-point both endpoints at a resolved entity by name, map `HANDLES` targets to `concern:<slug>`, drop self-loops, store `ALTERNATIVE_TO` one direction, then merge edges sharing `(source, type, target, source_chunk_id)`. Pure and deterministic. |
| `src/graph/queries.py` | Every Cypher string. `SCHEMA_STATEMENTS` (id constraints + name/type indexes), `WIPE`, 11 `ENTITY_TEMPLATES` (one per type — Cypher can't parameterise a label), 12 `RELATIONSHIP_TEMPLATES` (one per type, keyed on `source_chunk_id`; `HANDLES` targets a `:Concern` node), and count queries for gate checks. Templates are built once from the enums — the only place a type name is formatted into a string. |
| `src/graph/client.py` | `graph_client()` — the shared `Neo4jGraph` (one driver/process). `ensure_schema()`, `wipe()`. |
| `src/ingest/load_graph.py` | `load_graph(entities, relationships)` — MERGE each entity (its `properties` map is JSON-serialised because Neo4j properties must be primitive; `version` hoisted out), then each relationship via its template. Returns live DB counts. All MERGE → re-running changes nothing. |
| `scripts/ingest_corpus.py` | `chunk_corpus() → extract_corpus(skip=DEFERRED_CHUNKS) → resolve() → load_graph()`. `--wipe` for a clean rebuild. Prints the summary + type breakdowns and checks the gate ranges. `DEFERRED_CHUNKS` = 3 chunk IDs parked for a later top-up (see below); they're skipped, not extracted. Still pauses cleanly (exit 2) if a *non-deferred* chunk finds both providers rate-limited. |
| `scripts/backfill_extract.py` | One-off: extract the oversized chunks through **Gemini only** and write the result into `cache/llm.db` as the *first-attempt* Google cache row, so a normal Groq-primary ingest cache-hits the Google fallback leg for them. Never deletes a row; only writes a validated `ExtractionResult`. Run it once after quotas reset, then clear `DEFERRED_CHUNKS` and `--wipe`. |
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
tokens; Gemini 20 requests) and, mid-fix, wiped the Gemini cache for 3 of those
chunks. So: **39/42 chunks are in the graph now** (idempotent, `$0`, ~2 min to
rebuild from cache); the 3 in `DEFERRED_CHUNKS` get a one-shot
`backfill_extract.py` top-up once quotas reset. Provisional counts: **43
entities / 202 relationships** (targets 45–65 / 140–200).

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

## Phase 3 — Routing & retrieval ⬜

`src/pipeline/router.py`, `retrieve_graph.py`, `retrieve_vector.py`, `merge.py`,
`graph.py`.

## Phase 4 — Synthesis & API ⬜

`src/pipeline/synthesize.py`, `validate.py`, `src/api/main.py`, `dependencies.py`.

## Phase 5 — Benchmark & writeup ⬜

`src/baselines/vector_only.py`, `scripts/benchmark.py`, `BENCHMARK_RESULTS.md`,
`FINDINGS.md`, `SETUP.md`.
