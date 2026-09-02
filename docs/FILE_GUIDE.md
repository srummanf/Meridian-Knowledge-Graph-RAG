# File guide

One line per file. For the "why", see [`../PHASE_BUILD.md`](../PHASE_BUILD.md).

## `src/`

| File | Purpose |
|------|---------|
| `config.py` | The only module that builds provider clients. `Settings` from `.env`; `chat_model()` / `router_model()` / `extract_model()` / `embeddings()` factories with Groq→Google fallback; the SQLite LLM cache. |
| `logging_config.py` | One stdout handler, consistent format, quiets noisy libraries. |
| `models/domain.py` | Graph vocabulary: `EntityType` (11), `RelationType` (12), `DataConcern` (5). `Entity` / `Relationship`. `slugify()` + `make_entity_id()` for deterministic IDs. `CONFIDENCE_FLOOR`. |
| `models/extraction.py` | `ExtractionResult` — the schema handed to `with_structured_output` per chunk. |
| `models/routing.py` | `RoutingDecision` (`route`, `confidence`, `reasoning`, `entities_detected`) + `HYBRID_CONFIDENCE_FLOOR`. |
| `models/answer.py` | `Passage`, `GraphFact`, `MergedContext`, `Citation`, `GroundedAnswer` — the answer-side shapes. |
| `ingest/chunk.py` | Markdown → 42 chunks. One chunk per doc; split on `##` only for the few long docs, then pack sections into ~250-token sub-chunks. Stable `chunk_id`. |
| `ingest/extract.py` | `extract_chunk()` — structured-output LLM call, drop rows below the confidence floor, validate (evidence is a real substring, allowed properties, endpoints exist), retry ≤3 with the errors fed back. Handles Groq's per-request size ceiling by switching that chunk to Google. |
| `ingest/resolve.py` | `resolve()` — normalise names, apply the alias table, recompute deterministic IDs, merge duplicate entities and edges. Pure and deterministic. |
| `ingest/load_graph.py` | `load_graph()` — `MERGE` each entity and relationship via its template. Returns live DB counts. |
| `ingest/load_vector.py` | `vector_store()` (the `PGVector` handle), `entity_ids_by_chunk()`, `load_vector()` — embed locally and upsert keyed on `chunk_id`. |
| `graph/client.py` | `graph_client()` — the shared `Neo4jGraph`. `ensure_schema()`, `wipe()`. |
| `graph/queries.py` | **Every Cypher string.** Schema statements, 11 entity + 12 relationship `MERGE` templates (built from the enums), and 7 read templates for the retriever. |
| `pipeline/router.py` | `route_question()` — one few-shot structured-output call, then the `confidence < 0.70 → HYBRID` downgrade. |
| `pipeline/retrieve_graph.py` | `retrieve_graph()` — LLM fills a `GraphQueryPlan`, then deterministic: resolve anchors → pick a read template → run it → turn edges into sentences. |
| `pipeline/retrieve_vector.py` | `retrieve_vector()` — one `PGVector.similarity_search_with_score`, top-k `Passage`s. No LLM call. |
| `pipeline/merge.py` | `merge()` — dedupe passages and facts; `labelled_context()` renders the `GRAPH FACTS` / `RETRIEVED PASSAGES` block for synthesis. |
| `pipeline/synthesize.py` | `synthesize()` — one structured-output call producing an answer plus a `Citation` per claim. Empty context → fixed "not enough information". |
| `pipeline/validate.py` | `validate_answer()` — if a cited id is not in the retrieved set, regenerate once with an allow-list, keep the valid citations, note the drop. |
| `pipeline/graph.py` | The LangGraph `StateGraph`. `compile_pipeline` (retrieval only), `compile_answer_pipeline` (+ synthesize + validate), `run_pipeline` / `answer_question` singletons. |
| `baselines/vector_only.py` | `answer_vector_only()` — the full pipeline with the router pinned to `VECTOR`. The benchmark control. |
| `api/schemas.py` | `QueryRequest` + the non-200 response bodies. |
| `api/dependencies.py` | `datastore_status()` (never raises) and `require_datastores()` (the `/query` dependency that turns a DB outage into a 503). |
| `api/main.py` | FastAPI app: `POST /query`, `GET /health`, and the exception handlers that map errors to status codes. |
| `utils/errors.py` | One exception hierarchy; the API maps it to HTTP codes. |

## `scripts/`

| File | Purpose |
|------|---------|
| `check_setup.py` | Phase 0 gate — pings both DBs, the `vector` extension, local embeddings, and both LLMs. |
| `ingest_corpus.py` | The ingestion entry point: chunk → extract → resolve → load graph → load vectors. `--wipe` for a clean rebuild. |
| `benchmark.py` | Parse `data/benchmark/questions.md`, run both systems, write the resumable run file and the grading skeleton. |
| `score_benchmark.py` | Read the manual grades back, compute category means, check the Phase 5.2 gate. |

## `tests/`

One module per source module. Markers: `llm` (real cached LLM calls), `neo4j`,
`pgvector` (need the running containers; `test_load_graph` / `test_load_vector`
rebuild their indexes). `tests/fixtures/*.json` hold the labelled question sets.

## `data/`

The Meridian corpus (37 docs under topic folders) plus `ONTOLOGY.md` (the
vocabulary and alias table), `SCHEMA.md` (extraction contract), and
`benchmark/questions.md` (the 14 graded questions).
