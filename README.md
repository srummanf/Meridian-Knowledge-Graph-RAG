# Meridian Knowledge Graph RAG

Hybrid **knowledge-graph + vector RAG** over a 37-document technical corpus
(*Meridian*, a fictional fintech). Routes each question to graph traversal or
vector search, merges the results, and answers with validated citations.

> **Status:** in development. The benchmark table (Graph RAG vs. vector-only, by
> hop count) lands at the top of this file in Phase 5.

## Docs

- Planning & design: [`README_SPEC.md`](./README_SPEC.md)
- Corpus: [`data/README.md`](./data/README.md)
- Setup: see below (full `SETUP.md` in Phase 5)

## Quick start (Phase 0)

```bash
# 1. datastores
docker compose up -d          # Neo4j (7474/7687) + Postgres+pgvector (5432)

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
