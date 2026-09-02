# Folder structure

What every folder contains and what each file does. For *why* a file exists and
how it was built, see [`spec/BUILD_LOG.md`](./spec/BUILD_LOG.md).

```
.
├── README.md               project overview and reading order
├── LICENSE.md               MIT
├── CONTRIBUTING.md          conventions for a pull request
├── CLAUDE.md                notes for the AI pair-programmer used to build this
├── pyproject.toml           package metadata + dependencies + ruff/pytest config
├── docker-compose.yml       Neo4j 5 + Postgres 16/pgvector
├── .env.example             copy to .env, fill the two API keys
│
├── data/                    the corpus and its contract
├── src/                     the system
├── scripts/                 runnable entry points
├── tests/                   one test module per source module
├── docs/                    everything you are reading
└── cache/                   LLM response cache (git-ignored except .gitkeep)
```

---

## `data/` — the corpus

37 fabricated Markdown documents describing *Meridian*, plus the contract that
governs extraction.

| Path | Contents |
|------|----------|
| `cloud/`, `databases/`, `libraries/`, `products/`, `protocols/`, `security/`, `services/`, `teams/`, `vulnerabilities/` | the 37 corpus documents, one entity per file |
| `ONTOLOGY.md` | **single source of truth** — the 11 entity types, 12 relationship types, type precedence, alias table, ID scheme |
| `SCHEMA.md` | the extraction output JSON shape and validation rules |
| `benchmark/questions.md` | the graded benchmark questions with gold answers and rubric |
| `README.md` | corpus overview and the multi-hop chains it contains |

---

## `src/` — the system

### `src/config.py`, `src/logging_config.py`

`config.py` is the **only** module that constructs provider clients. It loads
`Settings` from `.env` and exposes `chat_model()`, `router_model()`,
`extract_model()`, `embeddings()` (Groq primary, Google fallback) and the SQLite
LLM cache. `logging_config.py` sets up one stdout handler.

### `src/models/` — Pydantic v2 shapes

| File | Contents |
|------|----------|
| `domain.py` | `EntityType`, `RelationType`, `DataConcern`; `Entity`, `Relationship`; `slugify()` / `make_entity_id()`; `CONFIDENCE_FLOOR` |
| `extraction.py` | `ExtractionResult` — the schema the extraction LLM fills per chunk |
| `routing.py` | `RoutingDecision` + `HYBRID_CONFIDENCE_FLOOR` |
| `answer.py` | `Passage`, `GraphFact`, `MergedContext`, `Citation`, `GroundedAnswer` |
| `__init__.py` | flat re-exports |

### `src/ingest/` — building the indexes

| File | Contents |
|------|----------|
| `chunk.py` | `chunk_corpus()` — 37 docs → 42 chunks with stable IDs |
| `extract.py` | `extract_chunk()` / `extract_corpus()` — structured-output extraction with validation and ≤3 retries; handles Groq's per-request size ceiling |
| `resolve.py` | `resolve()` — alias table, dedupe, deterministic IDs; pure and deterministic |
| `load_graph.py` | `load_graph()` — `MERGE` entities and relationships into Neo4j |
| `load_vector.py` | `vector_store()`, `load_vector()` — embed locally and upsert into pgvector keyed on `chunk_id` |

### `src/graph/` — Neo4j access

| File | Contents |
|------|----------|
| `client.py` | `graph_client()` (the shared `Neo4jGraph`), `ensure_schema()`, `wipe()` |
| `queries.py` | **every Cypher string** — 11 entity + 12 relationship write templates, plus 7 read templates for the retriever |

### `src/pipeline/` — the query pipeline

| File | Contents |
|------|----------|
| `router.py` | `route_question()` — classify into VECTOR / GRAPH / HYBRID / REFUSE |
| `retrieve_graph.py` | `retrieve_graph()` — LLM query plan → resolve → Cypher template → sentences |
| `retrieve_vector.py` | `retrieve_vector()` — exact cosine top-k passages |
| `merge.py` | `merge()` (dedupe both sources), `labelled_context()` (the synthesis prompt block) |
| `synthesize.py` | `synthesize()` — cited answer from the merged context |
| `validate.py` | `validate_answer()` — every cited id must be in the retrieved set, else one regeneration |
| `graph.py` | the LangGraph `StateGraph`; `run_pipeline()` (retrieval only), `answer_question()` (full pipeline) |

### `src/baselines/`

| File | Contents |
|------|----------|
| `vector_only.py` | `answer_vector_only()` — the full pipeline with the router pinned to VECTOR; the benchmark control |

### `src/api/` — FastAPI

| File | Contents |
|------|----------|
| `schemas.py` | request body + the non-200 response bodies |
| `dependencies.py` | `datastore_status()`, `require_datastores()` (the 503 guard) |
| `main.py` | `POST /query`, `GET /health`, and the exception handlers that map errors to status codes |

### `src/utils/`

| File | Contents |
|------|----------|
| `errors.py` | one exception hierarchy the API maps to HTTP codes |

---

## `scripts/` — entry points

| File | Run it to… |
|------|-----------|
| `check_setup.py` | verify the databases, the `vector` extension, embeddings, and both LLM providers |
| `ingest_corpus.py` | build the graph and the vector index (`--wipe` for a clean rebuild) |
| `ask.py` | ask the pipeline a question from the command line |
| `benchmark.py` | run the benchmark questions through both systems |
| `score_benchmark.py` | recompute the benchmark category means and gate from the graded results |
| `__init__.py` | makes `scripts/` importable so `tests/test_benchmark.py` can reuse the parser |

---

## `tests/`

One module per source module. `tests/fixtures/*.json` hold the labelled question
sets and the benchmark run data. Markers: `llm`, `neo4j`, `pgvector` gate the
tests that need external services. See [`spec/BUILD_LOG.md`](./spec/BUILD_LOG.md)
§ "Step 4 — Testing".

| Module | Covers |
|--------|--------|
| `test_models.py` | the Pydantic shapes |
| `test_chunk.py` | chunking |
| `test_extract.py` | extraction validation + retry (+ `llm` gate) |
| `test_resolve.py` | entity/edge resolution (the largest suite) |
| `test_load_graph.py` | graph load (+ `neo4j` gate, **wipes the graph**) |
| `test_load_vector.py` | vector load (+ `pgvector` gate, **rebuilds the collection**) |
| `test_router.py` | confidence floor + fixture hygiene (+ `llm` accuracy gate) |
| `test_retrieve_graph.py` | graph retriever + Cypher templates (+ `llm + neo4j` gate) |
| `test_retrieve_vector.py` | vector retriever + recall check (+ `pgvector` gates) |
| `test_merge.py`, `test_pipeline.py` | merge dedupe + LangGraph routing/fallbacks |
| `test_synthesize.py` | answer assembly (+ `llm + neo4j + pgvector` gate) |
| `test_validate.py` | citation validation (+ gate) |
| `test_api.py` | endpoint contract (+ one-request-per-route gate) |
| `test_benchmark.py` | benchmark parser + scorer (offline) |

---

## `docs/`

| Path | Contents |
|------|----------|
| `SETUP.md` | detailed local setup and platform gotchas |
| `WALKTHROUGH.md` | run every script and test, step by step, with expected output |
| `STRUCTURE.md` | this file |
| `BRIEF.md` | the original project brief, annotated with completion status |
| `results/FINDINGS.md` | the benchmark analysis |
| `results/BENCHMARK_RESULTS.md` | per-question graded results |
| `results/ROUTING_METRICS.md`, `results/API_METRICS.md` | one-run metric snapshots |
| `spec/PLAN.md` | the five-step build plan |
| `spec/BUILD_LOG.md` | file-by-file build log with rationale |
| `spec/architecture.md` | system design, data models, module responsibilities |
| `spec/prd.md`, `spec/rules.md` | the original requirements and coding rules |
| `spec/README_SPEC.md` | index to the spec documents |
