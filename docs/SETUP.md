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
python scripts/check_setup.py        # setup gate — pings both DBs + both LLMs + local embeddings
```

Expect a `PASS` line at the end.

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
python scripts/benchmark.py            # Graph RAG vs. vector-only
```

## Inspecting the data in a UI

You don't need much to look at what got ingested: Neo4j ships its own browser,
and Postgres needs one free SQL client. This section is the full walkthrough.

### Before you start

Both datastores must be running and populated:

```bash
docker compose up -d          # start Neo4j + Postgres (Docker Desktop must be running)
docker compose ps             # both rows should say "healthy"
python scripts/ingest_corpus.py --wipe   # only if the stores are empty
```

After a successful ingest you should see roughly:

| Store | What's in it |
|-------|--------------|
| **meridian-neo4j** | ~48 nodes (43 `:Entity` + 5 `:Concern`), ~222 relationships |
| **meridian-postgres** | ~42 rows in `langchain_pg_embedding` (one per chunk), 1 row in `langchain_pg_collection` |

The stack keeps running in the background until you stop it:

```bash
docker compose stop           # pause the containers, keep the data
docker compose down           # remove the containers, keep the named volumes
docker compose down -v        # also delete the data volumes (full reset)
```

---

### Neo4j — nothing to install

The `neo4j:5-community` image bundles the official **Neo4j Browser** web UI, so
there is nothing to download.

1. Open <http://localhost:7474> in any browser.
2. On the connect screen:
   - **Connect URL:** `bolt://localhost:7687`
   - **Authentication type:** Username / Password
   - **Username:** `neo4j`
   - **Password:** `meridian-dev`
   - Click **Connect**.
3. Type queries into the bar at the top and press <kbd>Ctrl</kbd>+<kbd>Enter</kbd>
   to run. Useful starting points:

   ```cypher
   MATCH (n) RETURN n LIMIT 100                       // draw a sample of the graph
   CALL db.schema.visualization()                     // the ontology: labels + edge types
   MATCH (n) RETURN labels(n)[0] AS label, count(*)   // node counts by label
     ORDER BY label
   MATCH ()-[r]->() RETURN type(r) AS rel, count(*)   // relationship counts by type
     ORDER BY count(*) DESC
   MATCH (a)-[r]->(b) RETURN a, r, b LIMIT 200        // sample of connected triples
   ```

4. Click any node in the result graph to expand its neighbours. Every node and
   edge carries a `source_chunk_id` property (edges also carry `evidence`) — that
   is the join key back to the corpus and to pgvector.

The results panel has **Graph**, **Table**, and **Text** views (icons on the
left edge of the panel). Switch to **Table** to read raw property values.

---

### Postgres + pgvector — one SQL client

The `embedding` column is a `vector(384)` (the pgvector type), so you need a
client that can talk to **PostgreSQL 16**. **DBeaver Community** is free,
cross-platform, and the one these instructions assume; pgAdmin 4, Beekeeper
Studio, and TablePlus all work with the same connection details.

**Install DBeaver Community:**

```bash
# Windows (winget)
winget install --id DBeaver.DBeaver.Community -e --accept-package-agreements --accept-source-agreements
# macOS (Homebrew)
brew install --cask dbeaver-community
# Linux / manual — https://dbeaver.io/download/
```

On Windows, winget installs it per-user; the executable lands at:

```
C:\Users\<you>\AppData\Local\DBeaver\dbeaver.exe
```

Launch it from the Start menu, or directly:

```powershell
& "$env:LOCALAPPDATA\DBeaver\dbeaver.exe"
```

**Create the connection:**

1. **Database ▸ New Database Connection** (or the plug-with-＋ icon, top-left).
2. Pick **PostgreSQL**, click **Next**.
3. Fill in the **Main** tab:

   | Field | Value |
   |-------|-------|
   | Host | `localhost` |
   | Port | **5433** (not the default 5432 — the container maps host 5433 → container 5432 to avoid clashing with a native Postgres) |
   | Database | `meridian` |
   | Username | `meridian` |
   | Password | `meridian-dev` |
   | Save password | tick it, so you're not re-prompted |

4. Click **Test Connection**. The first time, DBeaver offers to **download the
   PostgreSQL JDBC driver** — accept. You should get *Connected*.
5. Click **Finish**.

**Where the data is:**

Expand **meridian ▸ Schemas ▸ public ▸ Tables**. LangChain's `PGVector`
integration creates exactly two tables:

| Table | Rows | Columns of interest |
|-------|------|---------------------|
| `langchain_pg_collection` | 1 | `name` (the collection name), `uuid`, `cmetadata` |
| `langchain_pg_embedding` | ~42 (one per chunk) | `document` — the chunk text · `cmetadata` — JSON with `chunk_id`, `source`, headings · `embedding` — the 384-dim `vector` · `collection_id` — FK to the collection |

Double-click a table to open its **Data** grid. The `embedding` cell shows as a
long `[0.01, -0.03, …]` string; that's expected. Some example queries (open a SQL
editor with <kbd>Ctrl</kbd>+<kbd>]</kbd> or **SQL Editor ▸ New SQL script**):

```sql
-- how many chunks are indexed
SELECT count(*) FROM langchain_pg_embedding;

-- chunk text + its source document, from the JSON metadata
SELECT cmetadata ->> 'chunk_id'  AS chunk_id,
       cmetadata ->> 'source'    AS source,
       left(document, 120)       AS preview
FROM   langchain_pg_embedding
ORDER  BY source;

-- confirm the vector dimension
SELECT vector_dims(embedding) FROM langchain_pg_embedding LIMIT 1;
```

> DBeaver *can* also connect to Neo4j, but it needs the Neo4j JDBC/Cypher driver
> added by hand and renders graphs as tables. Use the bundled Neo4j Browser
> above for the graph.

---

### No UI — quick shell peek

If you just want the numbers without opening anything:

```bash
# Postgres
docker exec meridian-postgres psql -U meridian -d meridian -c "\dt"
docker exec meridian-postgres psql -U meridian -d meridian -c "SELECT count(*) FROM langchain_pg_embedding;"

# Neo4j
docker exec meridian-neo4j cypher-shell -u neo4j -p meridian-dev "MATCH (n) RETURN count(n) AS nodes;"
docker exec meridian-neo4j cypher-shell -u neo4j -p meridian-dev "MATCH ()-[r]->() RETURN count(r) AS rels;"
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
results incrementally and resumes — the benchmark itself was scoped down to 14
questions so a single $0 run finishes it.

## Windows notes

- Postgres is on **5433** (see above).
- First use of the local embedding model in a fresh process pings the Hugging
  Face Hub (~25 s, unauthenticated). Set `HF_HUB_OFFLINE=1` after the first
  successful run to skip it.
