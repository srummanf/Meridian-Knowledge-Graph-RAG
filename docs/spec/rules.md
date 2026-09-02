# Development Rules — Meridian Knowledge Graph RAG

**Version:** 3.0 · **Updated:** 2026-09-01

This is a rapid prototype. Lean on LangChain / LangGraph for the plumbing;
hand-write the router, the Cypher retrieval, and the citation validator. Rules
below keep even the framework code small, safe, and explainable.

---

## 1. Code quality

| Rule | Why |
|------|-----|
| Functions < 60 lines; modules < 300 | testable, explainable |
| Full type hints on every signature | FastAPI + LangGraph need them |
| Docstring on every public function | — |
| No magic numbers — module-level constants (`CONFIDENCE_FLOOR = 0.80`) | — |
| Catch specific exceptions; never bare `except:` | proper categorisation |
| Custom exceptions inherit `ApplicationError` (`utils/errors.py`) | one place → HTTP codes |
| Pydantic **v2** API (`model_validate`, `model_dump`) | LangChain is on v2 |
| `ruff` clean; `mypy` run, cheap issues fixed (not a hard gate) | — |

---

## 2. LangChain / LangGraph usage

### 2.1 One place builds models
`src/config.py` exposes `chat_model()`, `router_model()`, `embeddings()`. They
read `LLM_PROVIDER` and return the right LangChain object (`ChatGroq` or
`ChatGoogleGenerativeAI`, with `.with_fallbacks([...])` to the other;
`HuggingFaceEmbeddings`). Nothing else instantiates a provider class. There is no
local LLM fallback — if both providers are down, the call raises and the caller
surfaces the error (`/query` → 503).

### 2.2 Structured output, not string parsing
Extraction and routing use `model.with_structured_output(SomeModel)`. Don't
hand-parse JSON out of a completion.

### 2.3 Enable the LLM cache
`set_llm_cache(SQLiteCache("cache/llm.db"))` once at startup. Deterministic
prompts (extraction) then cost nothing on re-run. Delete `cache/` to force a
rebuild.

### 2.4 The query pipeline is a LangGraph `StateGraph`
Nodes: `route`, `retrieve_graph`, `retrieve_vector`, `merge`, `synthesize`,
`validate`. Conditional edges do routing and the graph→vector / vector→REFUSE
fallbacks. Keep each node a plain function `(state) -> partial state`.

### 2.5 Never `GraphCypherQAChain`
It generates Cypher with the LLM. We run **our own parameterized templates** via
`Neo4jGraph.query(TEMPLATE, params)`. This is a security control (no injection)
and makes results reproducible — and it's a deliberate, defensible choice to
explain.

---

## 3. Graph (Neo4j)

### 3.1 All Cypher lives in `src/graph/queries.py`
Named template strings. Callers pass parameters. No f-strings into queries, no
model-authored query strings anywhere.

### 3.2 One write template per relationship type
`-[r:$type]->` is invalid Cypher. Keep a dict:

```python
UPSERT_USES = """
MATCH (s:Entity {id: $source_id})
MATCH (t:Entity {id: $target_id})
MERGE (s)-[r:USES {source_chunk_id: $source_chunk_id}]->(t)
SET r.evidence = $evidence, r.confidence = $confidence, r.properties = $properties
"""
RELATIONSHIP_TEMPLATES = {"USES": UPSERT_USES, "DEPENDS_ON": UPSERT_DEPENDS_ON, ...}  # 12
```

### 3.3 MERGE, never CREATE
Entities: `MERGE (e:Entity {id:$id}) SET e += $props` + type label. Relationships:
`MATCH` endpoints, then `MERGE` keyed on `source_chunk_id`. Re-running ingestion
changes no counts.

### 3.4 Every element is cited
Entity → `source_chunk_id`. Relationship → `source_chunk_id` + `evidence` (the
exact sentence). Citation validation depends on this.

### 3.5 Deterministic IDs
`id = "<type_lowercase>:<slug(canonical_name)>"`. No UUIDs. (`ONTOLOGY.md` §4)

---

## 4. Ingestion

### 4.1 Cache by default
LLM calls via `SQLiteCache`; embeddings cached to `cache/embeddings/`. Re-runs
free and instant.

### 4.2 Validate every extraction
`ExtractionResult` parses; enums known; relationship properties are a subset of
what the type allows; `evidence` is a substring of the chunk (whitespace-
normalised); `confidence ∈ [0,1]`. Retry ≤ 3 with the error appended; then log
`chunk_id` to `failed_chunks` and continue.

### 4.3 Confidence floor
Drop any row with `confidence < 0.80`. Don't fail the chunk.

### 4.4 Explicit only
Extract a relationship only if a sentence states it. Never infer transitive
links — traversal does that at query time.

### 4.5 Track usage
Log input/output tokens per call and a notional cost even though free tiers make
it $0. Good habit, good talking point.

---

## 5. Retrieval, routing, synthesis

### 5.1 Router
`router_model.with_structured_output(RoutingDecision)`. `confidence < 0.70 →
HYBRID`. Log question + route + confidence for every call — the benchmark needs it.

### 5.2 Resolve entities before the graph query
LLM lists entity mentions → map to node ids via canonical name + alias table →
run a read template. Unknown entity → empty graph result → vector fallback.

### 5.3 Vector search is exact
No HNSW, no `ef_search`. `PGVector.similarity_search_with_score`, k small.
Sanity-check recall@5 on ~10 labelled queries (expect ≈ 1.0).

### 5.4 HYBRID merges both
Run both, concatenate, dedupe on `chunk_id` + near-duplicate text, pass both
labelled sets to synthesis.

### 5.5 Paths become sentences by template
`(A)-[:USES]->(B)` → "A uses B" via a per-type string template. No LLM call.

### 5.6 Citation per claim, validated
Every claim cites a `chunk_id`. After generation, every cited id must be in the
retrieved set. On failure, regenerate once with `Only cite from: [...]`. Then
return what validates with a note. Target 100% validity.

### 5.7 Labelled context
Graph facts and passages go under explicit headers (`GRAPH FACTS`,
`RETRIEVED PASSAGES`) so model and reader can tell them apart.

---

## 6. API

- Validate input with Pydantic (`question` non-empty, ≤ 1000 chars).
- Codes: `400` bad input, `422` out-of-scope, `503` DB down, `500` otherwise.
  Every error body: `error` + human `message`.
- Log latency per request; attach `latency_ms`.

---

## 7. Testing

Test what breaks silently:
- entity resolution — alias table, id generation, MERGE idempotency (ingest
  twice, counts unchanged)
- extraction validation — malformed response rejected + retried
- citation validator — invented `chunk_id` caught
- router — ≥ 90% on the labelled set
- one end-to-end `/query` test per route

Not required: >80% coverage, `mypy --strict` as a blocker, notebooks.

---

## 8. Logging

- `INFO`: ingest progress, entities resolved, routing decisions, query executed.
- `WARNING`: retries, fallbacks.
- `ERROR`: extraction failure after retries, invalid citation, DB errors (with context).
- Never log API keys. `.env` only; `.env` is gitignored.

---

## 9. Document your decisions

In a docstring or short comment, say why you chose X over Y — resolution
thresholds, router examples, chunking, and *why not `GraphCypherQAChain`*.
`FINDINGS.md` collects the big ones for the writeup.

---

## 10. Pre-commit checklist

- [ ] type hints + docstrings on new functions
- [ ] no function > 60 lines, no bare `except:`
- [ ] Cypher only via `queries.py` templates, parameters not interpolation
- [ ] provider classes only built in `config.py`
- [ ] new entities/relationships carry `source_chunk_id` (+ `evidence` for edges)
- [ ] `ruff` clean; tricky-path tests pass
- [ ] re-running ingestion changes nothing (idempotent)
