# Spec index

Planning documents for the Meridian Knowledge Graph RAG project. Read in order.

| # | Doc | Covers |
|---|-----|--------|
| 1 | [`prd.md`](./prd.md) | Why, users, features, success metrics, scope, resolved decisions |
| 2 | [`architecture.md`](./architecture.md) | Stack, file structure, models, API, module responsibilities, DB schema, LangGraph flow |
| 3 | [`rules.md`](./rules.md) | Code-quality and safety rules, framework-vs-hand-written boundary, checklist |
| 4 | [`phases.md`](./phases.md) | Phase 0–5 with tasks, gates, deliverables — the day-to-day plan |
| 5 | [`claude.md`](./claude.md) | How to drive the build with Claude Code |

## The corpus

| Doc | Covers |
|-----|--------|
| [`data/README.md`](./data/README.md) | Corpus overview, folder map, graph shape, multi-hop chains |
| [`data/ONTOLOGY.md`](./data/ONTOLOGY.md) | **Single source of truth** — entity/relationship types, precedence, alias table, ID scheme, targets |
| [`data/SCHEMA.md`](./data/SCHEMA.md) | Extraction output JSON shape + validation rules |
| [`data/benchmark/questions.md`](./data/benchmark/questions.md) | benchmark questions with gold answers + grading rubric (scoped to 14 for the free-tier run) |

## Snapshot

- **Corpus:** Meridian (fictional fintech), 37 docs, 11 entity types, 12
  relationship types.
- **Stack:** Python 3.11 · **LangChain + LangGraph** · FastAPI · Neo4j 5 ·
  pgvector · Groq (default) with Gemini fallback for generation (no local
  fallback — both down = endpoints error) · local `bge-small` (384-dim) for
  embeddings · Docker for the two DBs only.
- **Framework for the plumbing; hand-built** router + Cypher retrieval +
  citation validator. No `GraphCypherQAChain`, no HNSW tuning, no paid APIs, no
  app containerisation.
- **Deliverable:** `POST /query` with validated citations + a benchmark table
  (Graph RAG vs. vector-only, by hop count) at the top of `README.md`.
