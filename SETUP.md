# Setup — Meridian Knowledge Graph RAG

Local development on a single machine. ~10 minutes, $0 (both LLM providers have a
no-card free tier; embeddings run locally).

## Prerequisites

- **Docker** (Neo4j 5 + Postgres 16/pgvector run in containers)
- **Python 3.11+** (developed on 3.12)
- A **Groq** API key — <https://console.groq.com> (free, no card)
- A **Google AI Studio** key — <https://aistudio.google.com/apikey> (free; the
  automatic fallback when Groq is throttled)

## 1. Datastores

```bash
docker compose up -d
```

Brings up:

| Service | Host port | Notes |
|---------|-----------|-------|
| Neo4j | 7474 (browser), 7687 (bolt) | user `neo4j`, password `meridian-dev` |
| Postgres + pgvector | **5433** | 5433, not 5432 — avoids a native Postgres that may already own 5432 |

Wait for both to report healthy: `docker compose ps`.

## 2. Python environment

```bash
python -m venv .venv
. .venv/Scripts/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Scripts import `src.*`; pytest adds the repo root to `sys.path` automatically, but
for scripts either activate the venv or run them as
`PYTHONPATH=. python scripts/<name>.py`.

## 3. Secrets

```bash
cp .env.example .env
```

Fill `GROQ_API_KEY` and `GOOGLE_API_KEY`. Every other value has a default that
matches `docker-compose.yml`.

## 4. Verify

```bash
python scripts/check_setup.py        # Phase 0 gate — pings both DBs + both LLMs + local embeddings
```

Expect `Phase 0 gate: PASS`.

## 5. Build the indexes

```bash
python scripts/ingest_corpus.py --wipe
```

Chunks the 37-doc corpus (42 chunks), extracts entities/relationships with the
LLM, resolves and MERGEs them into Neo4j (43 entities, 222 relationships), and
embeds every chunk into pgvector (384-dim, local `bge-small`). The **LLM
extraction is cached** in `cache/llm.db`, so this is a ~2-minute, $0 rebuild on
every run after the first. Delete `cache/` to force a real re-extraction (slow,
and it can exhaust a free-tier daily quota — see below).

## 6. Run

```bash
uvicorn src.api.main:app --reload      # then POST /query, GET /health
python scripts/benchmark.py            # Graph RAG vs. vector-only (Phase 5)
```

## Testing

```bash
pytest -m "not llm and not neo4j and not pgvector"   # ~235 offline tests, fast
```

The `neo4j` / `pgvector` markers gate tests that need the running containers;
**`test_load_graph` and `test_load_vector` wipe and rebuild the live indexes**, so
after running the full marked suite, re-run `python scripts/ingest_corpus.py
--wipe` to restore them. The `llm` marker gates tests that make real (cached) LLM
calls.

## Free-tier reality

Free-tier **daily** token/request budgets are the binding constraint (Groq
~200 K tokens/day on `gpt-oss-120b`; Gemini ~20 requests/day). The design is
cache-first: build the extraction cache once, never re-run extraction against the
live APIs during iteration. A handful of larger chunks exceed Groq's per-request
ceiling and route to Gemini automatically. `scripts/benchmark.py` writes its
results incrementally and resumes, because one pass over all 30 questions × 2
systems will not fit in a single day's quota.

## Windows notes

- Postgres is on **5433** (see above).
- First use of the local embedding model in a fresh process pings the Hugging
  Face Hub (~25 s, unauthenticated). Set `HF_HUB_OFFLINE=1` after the first
  successful run to skip it.
