# Product Requirements — Meridian Knowledge Graph RAG

**Version:** 2.0 · **Status:** Planning · **Updated:** 2026-09-01

A learning project: build a retrieval system that answers questions about
enterprise software architecture by combining **vector search** (semantic) with
**knowledge-graph traversal** (relationships), routes each question to the right
path, and returns answers with validated citations.

The corpus is **Meridian**, a fictional fintech company's internal architecture
wiki (37 documents). See `data/README.md` and `data/ONTOLOGY.md`.

---

## 1. Why

Vector-only RAG retrieves passages by similarity. It does well on "what is X?"
and badly on anything that requires following relationships:

- *"If Log4Shell is exploited, which of our products are affected?"* — needs
  CVE → library → service → product.
- *"Which teams own a service that calls an API the Payments team owns?"* — needs
  team → service → API → service → team.
- *"How many services use PostgreSQL?"* — needs aggregation over edges.

A knowledge graph stores those relationships explicitly, so traversal answers
them directly. This project demonstrates the gap and measures it.

**What "done" looks like:** a FastAPI `/query` endpoint that returns grounded,
cited answers, and a `README.md` that opens with a benchmark table showing Graph
RAG matching vector RAG on 1-hop questions and pulling ahead as hop count rises.

---

## 2. Users

Software engineers and architects asking dependency/ownership/impact questions
about a technology estate. Secondary: the developer building this as a portfolio
piece and explaining it in interviews.

---

## 3. Features

### F1 — Knowledge graph construction
Extract entities and relationships from the corpus with a hosted LLM, validate
every response against a strict schema, resolve aliases to canonical entities,
write to Neo4j idempotently with a source-chunk citation on every element.

### F2 — Dual index
Embed the same chunks into pgvector. Both stores key on the same `chunk_id`, so a
graph path can link back to source text and a retrieved passage can link into the
graph.

### F3 — Question routing
A cheap LLM classifier routes each question to `VECTOR`, `GRAPH`, `HYBRID`, or
`REFUSE`. Low confidence → `HYBRID`. Every decision is logged.

### F4 — Graph retrieval
Resolve question entities to node IDs, then run a **parameterized Cypher
template** (never model-generated Cypher). Convert paths to readable sentences.

### F5 — Grounded synthesis
Merge graph facts and vector passages into one context with explicit source
labels. Generate an answer with a citation per claim. Validate every citation
resolves to a retrieved `chunk_id`; regenerate once if not.

### F6 — Benchmark
Run 30 stratified questions through Graph RAG and a vector-only baseline. Report
accuracy by hop count, plus latency and ingest cost. Table goes at the top of
`README.md`.

---

## 4. Success metrics

| Metric | Target | Notes |
|--------|--------|-------|
| Entity extraction F1 | ≥ 0.85 | vs. a hand-labelled gold set of the ~25 relationships the benchmark depends on |
| Relationship extraction F1 | ≥ 0.75 | same gold set |
| Alias-resolution (ONTOLOGY §3 cases) | 100% merged | curated corpus, deterministic |
| Router accuracy | ≥ 90% | on a ~20-question labelled set |
| 1-hop accuracy: Graph vs. vector | parity (±5%) | both should be strong here |
| 2-hop accuracy: Graph advantage | ≥ +15% over vector | |
| 3-hop / multi-constraint: Graph advantage | ≥ +30% over vector | the headline result |
| Aggregation accuracy | Graph ≥ 80%, vector ≈ 0% | vector structurally can't count |
| Citation validity | 100% | no invented sources |
| End-to-end latency | p95 < 3 s | soft target; depends on free-tier API latency |
| Ingest cost | $0 | free-tier APIs; ~20–30 min one-time run |

The numeric graph-size expectations (chunks, entities, relationships) live in
`data/ONTOLOGY.md` §6.

---

## 5. Scope

**In scope:** single fixed corpus, batch ingestion, English, the six features
above, a benchmark, documentation.

**Out of scope:** authentication on the API (assumes a trusted caller),
multi-corpus, real-time/incremental updates, linking entities to external KBs,
query-result caching, a UI, horizontal scaling / HA.

---

## 6. Constraints & assumptions

- **Rapid prototype.** LangChain + LangGraph for the plumbing and the query
  pipeline; hand-build only the router, the Cypher retrieval, and the citation
  validator (`architecture.md` §6).
- **Everything runs free.** LLM calls use Groq (default) with a Gemini fallback —
  both free tier, no card. No local LLM fallback: if both providers are down,
  ingestion and `/query` return an error rather than degrading silently.
  Embeddings run locally (`bge-small`). Two Docker containers (Neo4j, Postgres).
- Corpus is static, curated, authoritative, non-adversarial. Relationships are
  stated explicitly in the text (never implied).
- Solo developer, part-time, ~2–3 weeks.

---

## 7. Risks

| Risk | Mitigation |
|------|------------|
| Entity resolution misses variants → fragmented graph | Alias table in `ONTOLOGY.md` §3 seeded from the corpus; normalise + exact + alias match; add embedding-similarity dedup only if needed |
| Model emits raw Cypher → injection / non-reproducible | Our own parameterized templates via `Neo4jGraph.query()`; **not** LangChain's `GraphCypherQAChain`; no code path executes model-authored Cypher |
| One provider rate-limits / errors | LangChain retry/backoff → `.with_fallbacks()` to the other provider; `SQLiteCache` so re-runs are free and instant |
| Both providers down | Accepted failure mode — ingestion aborts (cache keeps progress), `/query` returns 503. No local fallback by choice. |
| Graph too sparse for multi-hop story | Corpus is authored with deliberate 3–4 hop chains (`ONTOLOGY.md` §7) |

---

## 8. Resolved decisions

| Question | Decision |
|----------|----------|
| Entity-type ambiguity (is PostgreSQL a Product or Database?) | Type-precedence list, `ONTOLOGY.md` §1 |
| Relationship vocabulary | 12 directional types, `ONTOLOGY.md` §2; `REQUIRES`/`USED_BY`/`INTEGRATES_WITH` removed |
| Entity resolution aggressiveness | exact + alias table + normalised form; no embedding dedup unless duplicates appear |
| Extract transitive relationships? | No — explicit only; transitivity is the traversal's job |
| Confidence scoring | model emits it; drop `< 0.80`; no re-rank |
| Router `HYBRID` behaviour | run both paths, concatenate + dedupe, let synthesis resolve |
| Graph path returns nothing | fall back to vector; if vector also empty → `REFUSE` |
| Chunking | one chunk per document; split by `##` section only if a doc exceeds ~350 tokens |
| Benchmark size | 30 questions, manually graded |

---

## 9. Definition of done

1. `docker-compose up` + `python scripts/ingest_corpus.py` populates Neo4j and
   pgvector from the Meridian corpus, idempotently.
2. `POST /query` returns a grounded answer with 100%-valid citations for
   in-scope questions and a clean refusal for out-of-scope ones.
3. Router ≥ 90% on the labelled set.
4. Benchmark run reproduces the widening-gap table; it is at the top of
   `README.md`.
5. Code follows `rules.md`; the tricky parts (resolution, validation, citations,
   router) have tests.
6. Every design decision is explainable from first principles.
