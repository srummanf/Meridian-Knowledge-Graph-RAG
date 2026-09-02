# Spec index

The planning documents for the Meridian Knowledge Graph RAG project. These are
build-time artifacts — the current state is described in the main
[`README.md`](../../README.md) and [`STRUCTURE.md`](../STRUCTURE.md).

| # | Doc | Covers |
|---|-----|--------|
| 1 | [`prd.md`](./prd.md) | why, features, scope, resolved decisions |
| 2 | [`architecture.md`](./architecture.md) | stack, data models, API, module responsibilities, DB schema, LangGraph flow |
| 3 | [`rules.md`](./rules.md) | code-quality and safety rules, the framework-vs-hand-written boundary |
| 4 | [`PLAN.md`](./PLAN.md) | the five-step build plan with tasks, gates, deliverables |
| 5 | [`BUILD_LOG.md`](./BUILD_LOG.md) | file-by-file log of what each module does and why |
| — | [`../../CLAUDE.md`](../../CLAUDE.md) | how the build was driven with an AI pair-programmer |

## The corpus

| Doc | Covers |
|-----|--------|
| [`../../data/README.md`](../../data/README.md) | corpus overview, folder map, the multi-hop chains it contains |
| [`../../data/ONTOLOGY.md`](../../data/ONTOLOGY.md) | **single source of truth** — entity/relationship types, precedence, alias table, ID scheme |
| [`../../data/SCHEMA.md`](../../data/SCHEMA.md) | extraction output JSON shape + validation rules |
| [`../../data/benchmark/questions.md`](../../data/benchmark/questions.md) | benchmark questions with gold answers + rubric (scoped to 14 for the free-tier run) |

## Snapshot

- **Corpus:** Meridian (fictional fintech), 37 docs, 11 entity types, 12
  relationship types.
- **Stack:** Python 3.11 · LangChain + LangGraph · FastAPI · Neo4j 5 · pgvector ·
  Groq with Gemini fallback for generation (no local fallback — both down means
  the endpoints error) · local `bge-small` (384-dim) embeddings · Docker for the
  two databases only.
- **Framework for the plumbing; hand-built** router + Cypher retrieval +
  citation validator. No `GraphCypherQAChain`, no HNSW tuning, no paid APIs.
- **Deliverable:** `POST /query` with validated citations + a benchmark table
  (Graph RAG vs. vector-only, by hop count) at the top of the README.
