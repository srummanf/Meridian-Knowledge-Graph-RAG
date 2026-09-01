# Architecture — Meridian Knowledge Graph RAG

**Version:** 3.0 · **Updated:** 2026-09-01

---

## 1. System overview

```
                         POST /query
                              │
                  ┌───────────▼────────────┐
                  │   FastAPI app           │
                  │   LangGraph pipeline:   │
                  │   route → retrieve →     │
                  │   merge → synth →        │
                  │   validate citations     │
                  └────┬──────────────┬─────┘
                GRAPH   │              │  VECTOR
              ┌─────────▼──┐     ┌─────▼───────┐
              │ Neo4j       │     │ pgvector     │
              │ (Neo4jGraph)│     │ (PGVector)   │
              └─────────────┘     └──────────────┘
                     │                   │
                     └────────┬──────────┘
                   grounded, cited answer
```

Ingestion (batch, run once): `data/*.md` → split → LLM structured extraction →
resolve aliases → Neo4j + pgvector, keyed on `chunk_id`.

**Framework stance:** this is a rapid-prototype. Use **LangChain** for the
plumbing (loaders, splitters, model wrappers, structured output, vector store,
Neo4j wrapper) and **LangGraph** for the query pipeline. Hand-write only the
three pieces that are the project's substance and its interview talking points:
the **router**, the **parameterized Cypher retrieval**, and the **citation
validator** (see §6).

---

## 2. Stack

| Concern | Choice | Notes |
|---------|--------|-------|
| Language | Python 3.11 | — |
| Orchestration | **LangChain + LangGraph** | query pipeline is a LangGraph `StateGraph` |
| API | FastAPI + uvicorn (local) | not containerised |
| Graph DB | Neo4j 5 Community (Docker) via `langchain-neo4j` `Neo4jGraph` | queries run through our own Cypher templates, **not** `GraphCypherQAChain` |
| Vector store | pgvector / Postgres 16 (Docker) via `langchain-postgres` `PGVector` | flat/exact search — no HNSW (~45 vectors) |
| LLM (extract, route, synth) | `langchain-groq` **default**, `langchain-google-genai` **fallback** | one factory in `config.py` picks the chat model; both free tier, $0. No local fallback — if both are down, `/query` and ingestion return an error. |
| Embeddings | `langchain-huggingface` `HuggingFaceEmbeddings` running `BAAI/bge-small-en-v1.5` locally (384-dim) | 130 MB, runs in ms on CPU |
| Extraction | `chat_model.with_structured_output(ExtractionResult)` | Pydantic v2 schema, provider-native JSON mode |
| Chunking | `langchain-text-splitters` `MarkdownHeaderTextSplitter` | one chunk per doc; splits on `##` when a doc is large |
| LLM cache | `langchain_core.globals.set_llm_cache(SQLiteCache("cache/llm.db"))` | re-runs are free and instant |
| Config | `pydantic-settings` + `.env` | |
| Tests | pytest | resolution, extraction, router, citations, one e2e per route |

### `.env.example`

```
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=meridian-dev
POSTGRES_DSN=postgresql+psycopg://meridian:meridian-dev@localhost:5432/meridian

LLM_PROVIDER=groq                      # groq | google  (primary; the other is the fallback)
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_ROUTER_MODEL=llama-3.1-8b-instant
GOOGLE_API_KEY=
GOOGLE_MODEL=gemini-2.0-flash

EMBED_MODEL=BAAI/bge-small-en-v1.5     # local, 384-dim
```

---

## 3. File structure

```
meridian-kg-rag/
├── pyproject.toml  .env.example  docker-compose.yml
├── README.md              # benchmark table on top (Phase 5 output)
├── prd.md  architecture.md  rules.md  phases.md  claude.md
├── data/                  # the Meridian corpus — see data/README.md
│   ├── ONTOLOGY.md  SCHEMA.md  README.md
│   ├── products/ services/ libraries/ databases/ cloud/
│   │   protocols/ security/ teams/ vulnerabilities/
│   └── benchmark/questions.md
├── src/
│   ├── config.py           # settings + chat_model() / router_model() / embeddings() factories
│   ├── logging_config.py
│   ├── models/             # domain.py extraction.py routing.py answer.py  (pydantic v2)
│   ├── ingest/
│   │   ├── chunk.py         # MarkdownHeaderTextSplitter wrapper, chunk_id assignment
│   │   ├── extract.py       # with_structured_output(ExtractionResult) + validation retry
│   │   ├── resolve.py       # alias table, deterministic ids, dedupe
│   │   ├── load_graph.py    # MERGE via templates
│   │   └── load_vector.py   # PGVector.add_documents
│   ├── graph/
│   │   ├── client.py        # Neo4jGraph wrapper + index setup
│   │   └── queries.py       # Cypher TEMPLATES (write: 12 MERGE; read: ~7)
│   ├── pipeline/
│   │   ├── graph.py         # LangGraph StateGraph wiring the nodes below
│   │   ├── router.py        # node: classify → RoutingDecision
│   │   ├── retrieve_graph.py# node: entities → ids → template → paths → sentences
│   │   ├── retrieve_vector.py# node: PGVector similarity search
│   │   ├── merge.py         # node: dedupe graph facts vs passages
│   │   ├── synthesize.py    # node: cited answer
│   │   └── validate.py      # node: citation check + one regeneration
│   ├── api/                 # main.py  dependencies.py
│   ├── baselines/           # vector_only.py  (Phase 5)
│   └── utils/               # errors.py
├── scripts/                 # ingest_corpus.py  benchmark.py  eval_extraction.py
├── tests/
└── cache/                   # gitignored: llm.db, embeddings/
```

---

## 4. Data models (Pydantic v2)

```python
# models/domain.py
EntityType = Literal["Product","Service","API","Library","Language","Database",
                     "CloudService","Protocol","SecurityMechanism","Team","Vulnerability"]
RelationType = Literal["PART_OF","DEPENDS_ON","USES","EXPOSES","CONSUMES",
                       "COMMUNICATES_VIA","SECURED_BY","DEPLOYED_ON","OWNED_BY",
                       "HANDLES","AFFECTS","ALTERNATIVE_TO"]

class Entity(BaseModel):
    id: str                       # "<type_lower>:<slug(canonical_name)>" — deterministic
    type: EntityType
    canonical_name: str
    aliases: list[str] = []
    properties: dict[str, Any] = {}
    confidence: float
    source_chunk_id: str

class Relationship(BaseModel):
    source_id: str; source_name: str
    type: RelationType
    target_id: str; target_name: str
    properties: dict[str, Any] = {}
    confidence: float
    evidence: str                 # exact substring of the chunk
    source_chunk_id: str

# models/extraction.py — the schema passed to with_structured_output()
class ExtractionResult(BaseModel):
    entities: list[Entity]
    relationships: list[Relationship]

# models/routing.py
class RoutingDecision(BaseModel):
    route: Literal["VECTOR","GRAPH","HYBRID","REFUSE"]
    confidence: float
    reasoning: str
    entities_detected: list[str] = []

# models/answer.py
class Citation(BaseModel):
    claim: str; chunk_id: str; source_type: Literal["VECTOR","GRAPH"]
class GroundedAnswer(BaseModel):
    question: str; answer: str
    citations: list[Citation]
    routing_used: Literal["VECTOR","GRAPH","HYBRID"]
    graph_paths: list[str] = []
    vector_passages: list[str] = []
    latency_ms: float
```

Vocabulary, precedence, alias table and the ID scheme are defined once in
`data/ONTOLOGY.md`.

### LangGraph pipeline state

```python
class QueryState(TypedDict):
    question: str
    routing: RoutingDecision | None
    graph_facts: list[str]
    vector_passages: list[Passage]
    context: str
    answer: GroundedAnswer | None
```

---

## 5. API contract

### `POST /query`

```json
// request
{ "question": "Which services use PostgreSQL?", "top_k": 5, "max_hops": 3 }

// 200
{
  "question": "...",
  "answer": "Five services use PostgreSQL: the Auth Service [services/auth-service.md], ...",
  "citations": [{ "claim": "The Auth Service uses PostgreSQL", "chunk_id": "services/auth-service.md", "source_type": "GRAPH" }],
  "routing_used": "GRAPH",
  "graph_paths": ["Auth Service USES PostgreSQL", "..."],
  "latency_ms": 1180
}

// 422 — out of scope
{ "error": "out_of_scope", "reason": "opinion", "message": "I answer architecture and ownership questions, not comparisons of merit." }
```

`400` empty/oversized input · `503` Neo4j or Postgres unreachable.

---

## 6. Module responsibilities

### Framework does it

- **`ingest/chunk.py`** — `MarkdownHeaderTextSplitter` on `#`/`##`; one chunk per
  document unless it exceeds ~350 tokens, then per `##` section.
  `chunk_id = "<relpath>"` or `"<relpath>#<slug>"`.
- **`ingest/extract.py`** — `chat_model.with_structured_output(ExtractionResult)`
  with a prompt built from `ONTOLOGY.md`. On a Pydantic/enum failure, retry ≤ 3
  with the error appended; then log to `failed_chunks`. Drop rows with
  `confidence < 0.80`; check `evidence` is a substring of the chunk.
- **`ingest/load_vector.py`** — `PGVector.add_documents`, metadata =
  `{chunk_id, document, entity_ids}`.
- **`pipeline/retrieve_vector.py`** — `PGVector.similarity_search_with_score`,
  exact (no HNSW).
- **`graph/client.py`** — `Neo4jGraph` for the connection + `.query()`.

### Hand-written (the substance)

- **`graph/queries.py`** — every Cypher string. 12 `MERGE` write templates (one
  per relationship type — Cypher can't parameterise a rel type), ~7 read
  templates (`entity_by_name`, `neighbors_1hop`, `path_2hop`, `two_constraint`,
  `count_by_relationship`, `blast_radius`, `owned_by_chain`). Executed with
  `Neo4jGraph.query(TEMPLATE, params)`. **We do not use `GraphCypherQAChain`** —
  it lets the model author Cypher against the DB (injection, non-reproducible).
- **`ingest/resolve.py`** — normalise name → apply `ONTOLOGY.md` §3 alias table →
  deterministic `id` → merge duplicates.
- **`pipeline/router.py`** — `router_model.with_structured_output(RoutingDecision)`,
  few-shot. `confidence < 0.70 → HYBRID`. Logs every decision.
- **`pipeline/retrieve_graph.py`** — LLM extracts entity mentions → resolve to
  ids → pick read template → execute → convert paths to sentences with per-type
  string templates (no LLM call).
- **`pipeline/validate.py`** — every cited `chunk_id` must be in the retrieved
  set; on failure regenerate once with an explicit allow-list; else return the
  claims that validate with a note.

---

## 7. Database schema

### Neo4j

```
(:Entity:{Type} { id, canonical_name, aliases, properties, confidence, source_chunk_id })
[:REL_TYPE { source_chunk_id, evidence, confidence, properties }]
```

- Deterministic `id` → `MERGE (e:Entity {id:$id}) SET e += $props` is idempotent.
- Relationship writes: `MATCH` both endpoints, then
  `MERGE (s)-[r:USES {source_chunk_id:$cid}]->(t) SET r += $props`. Keying on
  `source_chunk_id` stops duplicate parallel edges on re-run.
- `ALTERNATIVE_TO` written once, queried undirected.
- Indexes: `:Entity(id)`, `:Entity(canonical_name)`, `:Entity(type)`.

### Postgres / pgvector

`PGVector` manages its own tables (`langchain_pg_collection`,
`langchain_pg_embedding`). Embedding dimension **384** (`bge-small`). No HNSW
index — ~45 rows, exact scan is sub-ms and exact.

---

## 8. Ingestion flow (`scripts/ingest_corpus.py`)

```
docs = load data/**/*.md
for doc in docs:
    chunks = split(doc)                        # ingest/chunk
for chunk in chunks:
    result = extract(chunk)                    # ingest/extract (cached via SQLiteCache)
entities, rels = resolve(all_results)          # ingest/resolve
neo4j: MERGE entities, MERGE rels (templates)  # ingest/load_graph
PGVector.add_documents(chunks)                 # ingest/load_vector (bge-small, local)
verify: entity/edge counts, orphan check, every edge has source_chunk_id
```

---

## 9. Query flow (LangGraph `StateGraph`)

```
             ┌── route ──┐
             ▼            │ (conditional edge on routing.route)
   REFUSE ◄──┤            ├──► retrieve_vector ─┐
             ├──► retrieve_graph ───────────────┤
             └──► (HYBRID) both ────────────────┤
                                                ▼
                                              merge
                                                ▼
                                           synthesize
                                                ▼
                                        validate_citations ──(fail)──► synthesize (once)
                                                ▼
                                          GroundedAnswer

fallback edges: retrieve_graph empty → retrieve_vector ; retrieve_vector empty → REFUSE
```

---

## 10. Error handling

| Situation | Response |
|-----------|----------|
| Empty / >1000-char question | 400 |
| Router can't classify | HYBRID |
| Graph path empty | fall back to vector (logged) |
| Vector also empty | 422 REFUSE |
| Extraction invalid after 3 retries | log to `failed_chunks`, continue |
| Citation invalid after 1 regeneration | return validated subset + note |
| Neo4j / Postgres down | 503 |
| One LLM provider errors / rate-limited | retry with backoff, then switch to the other provider |
| **Both** LLM providers unavailable | `/query` → 503 `{"error":"llm_unavailable"}`; ingestion aborts with a clear message and the cache preserves progress |

---

## 11. Performance targets

| Step | Target |
|------|--------|
| Vector search (top-k) | < 50 ms |
| Graph traversal (≤3 hop) | < 200 ms |
| Router call | < 800 ms |
| Synthesis call | < 1.5 s |
| **End-to-end p95** | **< 3 s** (soft — free-tier API latency dominates) |
| Full ingest | < 30 min one-time, $0 |

---

## 12. Deployment

Local only. `docker-compose.yml` runs Neo4j + Postgres/pgvector with health
checks and named volumes. API: `uvicorn src.api.main:app`. A "how you'd
productionise this" paragraph goes in `FINDINGS.md`.
