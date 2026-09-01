# Meridian Knowledge Graph RAG

Hybrid **knowledge-graph + vector RAG** over a 37-document technical corpus
(*Meridian*, a fictional fintech). Routes each question to graph traversal or
vector search, merges the results, and answers with validated citations.

> **Status:** in development — Phase 1.3 complete. The benchmark table (Graph RAG
> vs. vector-only, by hop count) lands at the top of this file in Phase 5.

## Progress

| Phase | State | Output |
|-------|-------|--------|
| 0 — Setup | ✅ | DBs + LLM providers reachable, `check_setup.py` PASS |
| 1.1 — Models | ✅ | `src/models/*` — typed vocabulary & pipeline shapes (35 tests) |
| 1.2 — Chunking | ✅ | `src/ingest/chunk.py` — 37 docs → 42 chunks (15 tests) |
| 1.3 — Extraction | ✅ | `src/ingest/extract.py` + `src/utils/errors.py` — LLM → validated `ExtractionResult` (24 tests) |
| 1.4 — Graph load + resolution | 🚧 | code + tests done (53 tests); end-to-end ingest paused on Groq daily-token limit |
| 1.5 — Extraction eval | ⬜ | F1 ≥ 0.85 / 0.75 |
| 2 — Vector index | ⬜ | pgvector populated |
| 3 — Routing & retrieval | ⬜ | LangGraph pipeline |
| 4 — Synthesis & API | ⬜ | `POST /query` end to end |
| 5 — Benchmark & writeup | ⬜ | benchmark table, `FINDINGS.md` |

See [`PHASE_BUILD.md`](./PHASE_BUILD.md) for a file-by-file map of what each
module does and why.

## Docs

- File-by-file build log: [`PHASE_BUILD.md`](./PHASE_BUILD.md)
- Planning & design: [`README_SPEC.md`](./README_SPEC.md)
- Corpus: [`data/README.md`](./data/README.md)
- Setup: see below (full `SETUP.md` in Phase 5)

## Quick start (Phase 0)

```bash
# 1. datastores
docker compose up -d          # Neo4j (7474/7687) + Postgres+pgvector (host 5433)

# 2. python env
python -m venv .venv && . .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 3. secrets
cp .env.example .env          # then add GROQ_API_KEY and GOOGLE_API_KEY

# 4. gate check
python scripts/check_setup.py  # expect: Phase 0 gate: PASS
```

## Stack

Python 3.11 · LangChain + LangGraph · Neo4j 5 · pgvector · Groq (default) /
Gemini (fallback) for generation · local `bge-small` embeddings · FastAPI.
