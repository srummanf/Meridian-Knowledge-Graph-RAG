# Build plan

The plan the project was built to. Five steps, each with tasks, a gate, and the
files it produces. LangChain does the plumbing; LangGraph runs the query
pipeline; the router, Cypher retrieval, and citation validator are hand-written.

> The build history in [`BUILD_LOG.md`](./BUILD_LOG.md) still uses the original
> "Phase" numbering it was written under. The mapping: Phase 1 + Phase 2 &rarr;
> **Step 1**, Phase 3 + Phase 4.1/4.2 &rarr; **Step 2**, Phase 4.3 &rarr;
> **Step 3**, Phase 5 &rarr; **Step 5**.

---

## Getting started (½ day)

- `pyproject.toml`, `docker-compose.yml` (Neo4j 5 + Postgres 16/pgvector with
  health checks), `.env.example`.
- `src/config.py` — settings + `chat_model()` / `router_model()` /
  `embeddings()` factories + the SQLite LLM cache. `src/logging_config.py`.
- Free Groq API key; Google AI Studio key as the fallback.

**Gate:** `docker compose up` → both databases healthy; `python
scripts/check_setup.py` passes (pings both DBs, the `vector` extension, local
embeddings, both LLM providers).

---

## Step 1 — Data ingestion (about 1.5 weeks)

Turn 37 Markdown documents into a knowledge graph and a vector index that share a
`chunk_id` key.

### 1.1 Models
`src/models/{domain,extraction,routing,answer}.py` — Pydantic v2 shapes for
everything that flows through the pipeline. Enums match `data/ONTOLOGY.md`
exactly. **Gate:** models validate good data and reject bad (unknown enum,
out-of-range confidence).

### 1.2 Chunking ✅
`src/ingest/chunk.py` — `MarkdownHeaderTextSplitter`; one chunk per document,
split on `##` only if a doc exceeds ~280 tokens, then sections packed into
~250-token sub-chunks. `chunk_id = "<relpath>"` or `"<relpath>#<slug>"`.
**Gate:** 37 docs → 40–55 chunks (currently 42), unique ids, non-empty content.

### 1.3 Extraction ✅
`src/ingest/extract.py` — prompt built from `data/ONTOLOGY.md` + the `SCHEMA.md`
example; `chat_model.with_structured_output(ExtractionResult)` (Groq needs
`method="json_schema"`). Validation — enum, evidence is a real substring,
confidence floor, allowed properties, endpoints exist — with ≤3 retries feeding
the errors back. Exhausted chunks are recorded, not raised. Cached in
`cache/llm.db`. **Gate:** clean run on three service docs
(`tests/test_extract.py -m llm`); a corrupted response is rejected and retried;
a second run is a cache hit.

### 1.4 Resolution and graph load ✅ — 42/42 chunks live
`src/ingest/resolve.py` (normalise → alias table → dedupe → deterministic id),
`src/graph/queries.py` (11 entity + 12 relationship `MERGE` templates built from
the enums), `src/graph/client.py`, `src/ingest/load_graph.py`.
`scripts/ingest_corpus.py --wipe` runs the whole chain; it pauses cleanly
(exit 2) if both LLM providers are throttled.

**Free-tier note:** Groq's free tier caps a single request at ~8000 tokens/min;
about eight larger chunks exceed that and route to Gemini automatically.

**Gate met:** Neo4j holds **43 entities, 222 relationships**. The entity count is
just under the planned 45–65 (the corpus really has 43 distinct nodes); the edge
count is above the planned 140–200 because edges are keyed on `source_chunk_id`
for provenance (a fact in N documents is N edges; distinct `(src, type, tgt)`
triples ≈ 130). Every alias case resolves to one node. Re-running the ingest
changes zero rows. Every relationship carries `source_chunk_id` and `evidence`.
Ingest is under 20 minutes and $0 (about 2 minutes from cache).

### 1.5 Vector index and recall check ✅
`src/ingest/load_vector.py` — `HuggingFaceEmbeddings("BAAI/bge-small-en-v1.5")`
(local), `PGVector.add_documents(ids=[chunk_id])` (upsert), metadata
`{chunk_id, document, entity_ids}`, collection `meridian_chunks`, cosine,
384-dim, **no ANN index**. Wired into `ingest_corpus.py`.
`tests/fixtures/vector_eval.json` holds 12 `(question → gold chunk)` pairs;
`tests/test_retrieve_vector.py` measures recall. **Gate met:** all 42 chunks
embedded; `chunk_id` is the shared key; re-run changes nothing; **recall@1 =
1.00** (n=12). Why no ANN index: with ~42 vectors an exact scan is sub-ms and
recall-1.0 by construction — HNSW would only add build time and approximation
error.

### 1.6 Extraction eval — not built
Planned: hand-label the ~25 benchmark-critical relationships and report
precision/recall/F1. Would catch the known bug where every `USES PostgreSQL`
edge is attributed to the CVE document. On the roadmap.

---

## Step 2 — RAG pipeline (about 1.5 weeks)

Route a question, retrieve, merge, synthesize a cited answer, validate the
citations. All wired as a LangGraph `StateGraph`.

### 2.1 Router ✅
`src/pipeline/router.py` — one `router_model.with_structured_output(RoutingDecision)`
call, 12-example few-shot prompt, then `confidence < 0.70 → HYBRID`. Logs every
decision. **Gate met:** **95.2%** (20/21) on `tests/fixtures/routing_eval.json`
(disjoint from the few-shot). The single miss is a GRAPH/VECTOR borderline.
`tests/test_router.py`. Confusion matrix in
[`../results/ROUTING_METRICS.md`](../results/ROUTING_METRICS.md).

### 2.2 Graph retriever ✅
`src/pipeline/retrieve_graph.py` — one structured-output call fills a
`GraphQueryPlan` (the model never writes Cypher) → resolve anchors → pick a
generic read template → `Neo4jGraph.query()` → per-relationship-type sentences.
Templates in `src/graph/queries.py`: `RESOLVE_ENTITY(_FUZZY)`, `NEIGHBORS`,
`COUNT_NEIGHBORS`, `TWO_CONSTRAINT`, `PATH_BETWEEN`, `BLAST_RADIUS`. The
relationship type is a `$rel` parameter, never interpolated. **Gate met:**
B09/B14/B16/B17/B24 return the exact gold node sets; Cypher runs in 12–56 ms
(budget 200). `tests/test_retrieve_graph.py` + `tests/fixtures/graph_eval.json`.

### 2.3 Vector retriever ✅
`src/pipeline/retrieve_vector.py` — one
`PGVector.similarity_search_with_score` (exact cosine), top-k `Passage`s, no LLM
call. **Gate met:** B01–B08 all rank 1 in the top 3.

### 2.4 Merge and LangGraph wiring ✅
`src/pipeline/merge.py` — dedupe passages (best score per `chunk_id`, then
near-duplicate text) and facts; `labelled_context()` renders `GRAPH FACTS` /
`RETRIEVED PASSAGES` headers. `src/pipeline/graph.py` — the `StateGraph`:
`route` → conditional → `retrieve_graph` / `retrieve_vector` → `merge`, with
fallbacks (HYBRID or graph empty → vector; nothing retrieved → REFUSE). Linear
even for HYBRID. **Gate met:** every route and both fallbacks covered.
`tests/test_merge.py`, `tests/test_pipeline.py`.

### 2.5 Synthesis ✅
`src/pipeline/synthesize.py` — one
`chat_model.with_structured_output(SynthesisResult)` call over the labelled
context; a `Citation{claim, chunk_id, source_type}` per claim, chunk id copied
from a `[bracket]`. Empty context → a fixed "not enough information", no call.
**Gate met:** 5/5 sample answers coherent, every citation in the retrieved set.
`tests/test_synthesize.py`.

### 2.6 Citation validation ✅
`src/pipeline/validate.py` — `validate_answer()`: if every cited id is in
`context.chunk_ids`, return unchanged; otherwise regenerate **once** with a
`Cite ONLY from: […]` allow-list, keep the valid citations, drop the rest with a
note. `graph.py::compile_answer_pipeline` wires the retrieval subgraph →
`synthesize` → `validate`; `answer_question(q)` is the singleton entry point.
**Gate met:** 100% cited-source validity on the sample; an injected fake
citation is caught. `tests/test_validate.py`.

---

## Step 3 — API (2–3 days)

`src/api/{main,schemas,dependencies}.py` — `POST /query` (200 `GroundedAnswer` /
422 out-of-scope / 400 bad input / 503 datastore down via `require_datastores`),
`GET /health`. Invokes `answer_question`. **Gate met:** one integration test per
route. Latency snapshot in
[`../results/API_METRICS.md`](../results/API_METRICS.md) (measured warm — a cold
free-tier call adds 5–120 s of rate-limit back-off). `tests/test_api.py`,
`scripts/ask.py` (CLI).

---

## Step 4 — Testing (continuous)

One test module per source module under `tests/`, plus fixture question sets.
Markers gate the tests that need external services: `llm` (real cached LLM
calls), `neo4j`, `pgvector`. Offline suite: **237 tests**, runs in ~20 s.

```bash
pytest -m "not llm and not neo4j and not pgvector"   # offline
pytest -m "llm or neo4j or pgvector"                 # integration gates
```

`test_load_graph.py` and `test_load_vector.py` rebuild their indexes — re-run
`python scripts/ingest_corpus.py --wipe` after the full marked suite.

---

## Step 5 — Benchmark and findings (4–5 days)

### 5.1 Baseline and harness ✅
`src/baselines/vector_only.py` — the identical pipeline with the router pinned to
`VECTOR`, so the graph never runs and it is a fair control.
`scripts/benchmark.py` parses `data/benchmark/questions.md` into a fixture, runs
each question through both systems, and writes a resumable run file plus a
grading skeleton. `scripts/score_benchmark.py` reads the grades back and checks
the gate. `tests/test_benchmark.py`.

### 5.2 Grade and analyse ✅ — gate NOT met; that is the finding
The question set was scoped to **14** — what one $0 free-tier run completes.
Graded per category (graph / vector): 1-hop 0.84 / 0.84 (parity), 2-hop
1.00 / 1.00, 3-hop 0.75 / 0.75, aggregation 1.00 / 1.00, refusal 1.00 / 1.00 —
**Δ ≈ 0.00 everywhere.** Two structural causes: the corpus pre-aggregates its
relationships, so vector answers nominal multi-hop from a single document; and
one true 3-hop question fits none of the six query-plan shapes. Full analysis in
[`../results/FINDINGS.md`](../results/FINDINGS.md).

### 5.3 Writeup ✅
Benchmark table at the top of the README;
[`../results/FINDINGS.md`](../results/FINDINGS.md) (corpus pre-aggregation, the
template ceiling, where the graph wins and loses, cost and latency honesty, why
`GraphCypherQAChain` is not used); [`../SETUP.md`](../SETUP.md).

---

## Résumé line

> Built a hybrid knowledge-graph + vector RAG system (LangGraph, Neo4j, pgvector,
> Groq) over a 37-document corpus: an LLM router, a security-reviewed
> Cypher-template retriever (no model-authored queries), and a citation validator
> that holds 100% cited-source validity. Benchmarked it head-to-head against a
> vector-only baseline and reported the honest result — parity on this corpus,
> because the source documents pre-aggregate their relationships, plus a
> template-coverage ceiling on genuine multi-hop questions.
