# Meridian Knowledge Graph RAG

A retrieval system that answers questions about software architecture by
combining **vector search** with **knowledge-graph traversal**. Each question is
routed to the strategy that fits it, the results are merged, and the answer comes
back with a citation for every claim.

The corpus is *Meridian*, a fictional fintech company's internal architecture
wiki (37 Markdown documents describing services, APIs, libraries, datastores,
teams, and two CVEs).

This is a learning project. It was built to understand RAG, Graph RAG, knowledge
extraction with LLMs, Neo4j, pgvector, and LangGraph end to end — and to
measure, honestly, whether a knowledge graph actually beats plain vector search
on this kind of corpus.

![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Neo4j](https://img.shields.io/badge/Neo4j-5-008CC1?logo=neo4j&logoColor=white)
![pgvector](https://img.shields.io/badge/pgvector-Postgres%2016-4169E1?logo=postgresql&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangChain%20%2B%20LangGraph-1C3C3C)
![Tests](https://img.shields.io/badge/tests-237%20offline%20%2B%20integration%20gates-brightgreen)
![Lint](https://img.shields.io/badge/lint-ruff-D7FF64)
![License](https://img.shields.io/badge/license-MIT-blue)
![Cost](https://img.shields.io/badge/API%20cost-%240-success)

---

## Result

The graph did **not** beat the vector-only baseline on answer accuracy for this
corpus. The Meridian documents are densely cross-referenced (a database's page
lists every service that uses it), so vector search answers "multi-hop" questions
from a single page. The graph still wins on citation precision, refusal handling,
and questions no single document answers. Full analysis in
[`docs/results/FINDINGS.md`](./docs/results/FINDINGS.md).

| Category | Graph | Vector |
|----------|------:|-------:|
| 1-hop / definitional | 0.84 | 0.84 |
| 2-hop | 1.00 | 1.00 |
| 3-hop | 0.75 | 0.75 |
| aggregation | 1.00 | 1.00 |
| refusal | 1.00 | 1.00 |

A negative result, reported as a result. That is the point of the benchmark.

---

## Where to start

Read in this order.

| # | Document | For |
|---|----------|-----|
| 1 | [`docs/SETUP.md`](./docs/SETUP.md) | install everything and verify it works |
| 2 | [`docs/WALKTHROUGH.md`](./docs/WALKTHROUGH.md) | run the pipeline and the tests, step by step, with expected output |
| 3 | [`docs/STRUCTURE.md`](./docs/STRUCTURE.md) | what every folder and file does |
| 4 | [`docs/spec/architecture.md`](./docs/spec/architecture.md) | the system design |
| 5 | [`docs/results/FINDINGS.md`](./docs/results/FINDINGS.md) | the benchmark analysis — where the graph wins and loses |
| 6 | [`docs/BRIEF.md`](./docs/BRIEF.md) | the original brief, annotated with what shipped |

The rest of this README is the summary: features, architecture diagrams, the
five build steps, and the API reference.

---

## Tech stack

[![skills](https://skillicons.dev/icons?i=python,fastapi,postgres,neo4j,docker,git)](https://skillicons.dev)

- **Orchestration:** LangChain, LangGraph (`StateGraph` query pipeline)
- **Graph store:** Neo4j 5 (Community), accessed only through parameterised
  Cypher templates
- **Vector store:** Postgres 16 + `pgvector` (exact cosine scan, 384-dim, no ANN
  index)
- **Embeddings:** `BAAI/bge-small-en-v1.5`, run locally — no API call
- **LLMs:** Groq (`gpt-oss-120b` / `gpt-oss-20b`) with Google Gemini as an
  automatic fallback; both on the free tier
- **API:** FastAPI + Uvicorn
- **Tooling:** pytest, ruff, Docker Compose

---

## Features

- **Question router** — one small LLM call classifies each question as
  `VECTOR`, `GRAPH`, `HYBRID`, or `REFUSE` before any retrieval runs. 95% accurate
  on a labelled set.
- **Graph retriever** — the LLM fills a typed query plan (which entity, which
  edge, which direction); the code maps that to one of seven reviewed Cypher
  templates. The model never writes Cypher against the database.
- **Vector retriever** — exact cosine similarity over ~42 chunks; recall@1 = 1.00
  on the sanity set.
- **Merge + labelled context** — graph facts and passages are deduped and passed
  to synthesis under explicit `GRAPH FACTS` / `RETRIEVED PASSAGES` headers.
- **Cited synthesis** — every claim in the answer carries a `chunk_id`.
- **Citation validator** — any cited source not in the retrieved set triggers one
  regeneration with an allow-list; leftover bad citations are dropped with a note.
  100% cited-source validity on the sample.
- **Deterministic, idempotent ingestion** — deterministic IDs + `MERGE` mean
  re-running the ingest changes zero rows. Extraction is cached, so a full
  rebuild is about two minutes and costs nothing.

---

## Architecture

The build follows a strict split:

- **The framework does the plumbing** — loaders, splitters, model wrappers,
  structured output, `PGVector`, `Neo4jGraph`, the `StateGraph` runtime.
- **The interesting parts are hand-written** — the router, the graph query
  planner and Cypher templates, the entity resolver, and the citation validator.

`GraphCypherQAChain` is deliberately not used: letting an LLM author Cypher
against a live database is an injection risk and makes results non-reproducible.
A typed plan mapped to fixed templates trades some coverage for safety.

See [`docs/spec/architecture.md`](./docs/spec/architecture.md) for the full
design and [`docs/spec/BUILD_LOG.md`](./docs/spec/BUILD_LOG.md) for a file-by-file
build log.

### Ingestion (one-time, cached)

```mermaid
flowchart LR
    D["37 Markdown docs"] --> C["chunk<br/>42 chunks"]
    C --> E["extract<br/>LLM + validate"]
    E --> R["resolve<br/>alias table, dedupe,<br/>deterministic IDs"]
    R --> G[("Neo4j<br/>43 entities, 222 rels")]
    C --> V["embed<br/>bge-small, local"]
    V --> P[("pgvector<br/>42 vectors")]
```

### Query pipeline (LangGraph `StateGraph`)

```mermaid
flowchart TD
    Q["question"] --> RT{"route (LLM)"}
    RT -->|REFUSE| X["422 out of scope"]
    RT -->|VECTOR| RV["retrieve_vector"]
    RT -->|GRAPH / HYBRID| RG["retrieve_graph<br/>plan, resolve, Cypher, sentences"]
    RG -->|graph empty / HYBRID| RV
    RG --> M["merge<br/>dedupe + label"]
    RV --> M
    M --> S["synthesize<br/>LLM, cited answer"]
    S --> VAL["validate<br/>cited ids must be in retrieved set"]
    VAL --> A["GroundedAnswer"]
```

---

## Folder structure

```
.
├── data/         Meridian corpus (37 docs) + ontology, schema, benchmark
├── src/          the system: models, ingest, graph, pipeline, baselines, api
├── scripts/      check_setup, ingest_corpus, ask, benchmark, score_benchmark
├── tests/        one test module per source module + fixtures/
└── docs/         setup, walkthrough, structure, results/, spec/
```

Full explanation — every folder and file — in
[`docs/STRUCTURE.md`](./docs/STRUCTURE.md).

---

## Requirements

- Python 3.11 or 3.12
- Docker (for Neo4j and Postgres)
- A free [Groq](https://console.groq.com) API key
- A free [Google AI Studio](https://aistudio.google.com/apikey) API key (fallback)

No GPU. Embeddings run on CPU.

---

## Run locally

```bash
# 1. datastores
docker compose up -d

# 2. environment
python -m venv .venv && . .venv/Scripts/activate   # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"

# 3. secrets
cp .env.example .env                                # then fill GROQ_API_KEY and GOOGLE_API_KEY

# 4. verify setup
python scripts/check_setup.py                       # expect a PASS line at the end

# 5. build the indexes (about 2 minutes, $0 from cache)
python scripts/ingest_corpus.py --wipe

# 6. ask a question
python scripts/ask.py "Which services use PostgreSQL?"
```

Detailed notes (Windows Postgres port clash, Hugging Face cold start, free-tier
limits) are in [`docs/SETUP.md`](./docs/SETUP.md).

---

## Demo

```bash
python scripts/ask.py "If Log4Shell is exploited, which Meridian products are affected?"
```

```
route:   GRAPH
latency: 8670 ms

Ledger Service and Payments Platform are affected.

sources:
  - [GRAPH] libraries/log4j.md
  - [GRAPH] vulnerabilities/cve-2021-44228-log4shell.md
```

```bash
python scripts/ask.py "Is PostgreSQL better than MySQL?"
```

```
route:   REFUSE
answer:  Out of scope. This system answers questions about Meridian's architecture
         and ownership, not opinions, forecasts, or costs.
```

`--json` prints the raw `GroundedAnswer`. To serve the HTTP API instead:
`uvicorn src.api.main:app` and open `http://localhost:8000/docs`.

A full walkthrough — every script and test from Step 1 to Step 5, with expected
output — is in [`docs/WALKTHROUGH.md`](./docs/WALKTHROUGH.md).

```bash
pytest -m "not llm and not neo4j and not pgvector"   # 237 offline tests, ~20 s
```

---

## Inspecting the databases in a UI

With `docker compose up -d` running and the indexes built (`docker compose ps`
shows both healthy), you can browse both stores visually.

### Neo4j — nothing to install

The `neo4j:5-community` image bundles the **Neo4j Browser** web UI.

1. Open <http://localhost:7474>.
2. Connect URL `bolt://localhost:7687`, auth *Username / Password*, user `neo4j`,
   password `meridian-dev`.
3. Run queries (<kbd>Ctrl</kbd>+<kbd>Enter</kbd>):

   ```cypher
   MATCH (n) RETURN n LIMIT 100                      // ~48 nodes
   MATCH ()-[r]->() RETURN type(r), count(*)         // ~222 relationships
   CALL db.schema.visualization()                    // the ontology
   ```

### Postgres + pgvector — one SQL client

Install **DBeaver Community** (free, cross-platform):

```bash
winget install --id DBeaver.DBeaver.Community -e     # Windows  → %LOCALAPPDATA%\DBeaver\dbeaver.exe
brew install --cask dbeaver-community                # macOS
# Linux / manual: https://dbeaver.io/download/
```

**Database ▸ New Database Connection ▸ PostgreSQL**, then:

| Field | Value |
|-------|-------|
| Host | `localhost` |
| Port | **5433** (not 5432) |
| Database | `meridian` |
| Username | `meridian` |
| Password | `meridian-dev` |

**Test Connection** → accept the JDBC driver download → **Finish**. The data
sits under **meridian ▸ Schemas ▸ public ▸ Tables**:

| Table | Rows | Holds |
|-------|------|-------|
| `langchain_pg_collection` | 1 | collection metadata |
| `langchain_pg_embedding` | ~42 | one row per chunk: `document` text, `cmetadata` JSON (`chunk_id`, `source`), `embedding` `vector(384)` |

pgAdmin 4, Beekeeper Studio, and TablePlus work with the same credentials.

### Stopping the stack

```bash
docker compose stop     # pause, keep data
docker compose down      # remove containers, keep volumes
docker compose down -v   # full reset — deletes the data too
```

Full walkthrough (step-by-step DBeaver setup, example SQL/Cypher, shell
one-liners) in
[`docs/SETUP.md`](./docs/SETUP.md#inspecting-the-data-in-a-ui).

---

## API reference

### `POST /query`

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `question` | string | — | 1–1000 characters, required |
| `top_k` | int | 5 | reserved; the pipeline uses its own default |
| `max_hops` | int | 3 | reserved |

Responses:

| Status | Body | When |
|--------|------|------|
| `200` | `GroundedAnswer` (`answer`, `citations[]`, `routing_used`, `graph_paths[]`, `vector_passages[]`, `notes[]`, `latency_ms`) | answered |
| `422` | `{ error: "out_of_scope", reason, message }` | router refused (opinion, forecast, out of domain) |
| `400` | `{ error: "bad_request", message }` | empty or oversized question |
| `503` | `{ error: "unavailable", message }` | Neo4j or Postgres unreachable |

### `GET /health`

`200` with `{ status: "ok" | "degraded", neo4j, postgres }` — `200` even when a
store is down; the body says which.

Interactive docs at `/docs` when the server is running.

---

## Build steps

The project was built in five steps. The plan is
[`docs/spec/PLAN.md`](./docs/spec/PLAN.md); the file-by-file log is
[`docs/spec/BUILD_LOG.md`](./docs/spec/BUILD_LOG.md).

| Step | What | State |
|------|------|-------|
| Setup | Docker, config, `check_setup.py` | done |
| 1 — Data ingestion | chunk → extract → resolve → load Neo4j + pgvector | done (42/42 chunks, 43 entities, 222 relationships) |
| 2 — RAG pipeline | router, retrievers, merge, synthesize, validate, LangGraph | done (router 95%, 100% citation validity) |
| 3 — API | `POST /query`, `GET /health`, `scripts/ask.py` | done |
| 4 — Testing | one test module per source module + integration gates | done (237 offline + gates) |
| 5 — Benchmark | vector-only baseline, run, grade, analyse | done (parity — see the Result above) |

Open items are in the Roadmap below. The extraction eval (a labelled F1 check)
was planned but not built.

---

## Roadmap

All five steps are complete. Known open items, in rough priority order:

- **Extraction eval** — a labelled precision/recall/F1 check on the ~25
  benchmark-critical relationships. Would catch the known citation-attribution
  bug where every `USES PostgreSQL` edge points at the CVE document.
- **A `chain` query template** — a bounded variable-length path with typed
  endpoints, to cover genuine 3-hop questions (the one benchmark question the
  current six query-plan shapes cannot express).
- **Run the full 30-question benchmark** on a paid LLM tier (the set was cut to
  14 to fit the free-tier daily quota).
- **HNSW index** — only once the corpus is 10⁴+ vectors; irrelevant at 42.

---

## Lessons learned

- **RAG is retrieval *plus generation*.** Vector search and graph traversal only
  find context; an LLM still has to write the cited answer. That call is the cost
  and latency floor, not the retrieval.
- **Graph RAG is not automatically better.** Its advantage depends on the corpus.
  If the source documents already aggregate their relationships, plain vector
  search matches it. The graph earns its keep on distributed facts, exact-set
  completeness, and aggregation.
- **Constrain the LLM's authority.** A typed query plan mapped to reviewed Cypher
  templates is safer and more reproducible than letting the model write queries —
  at the cost of coverage for question shapes nobody templated.
- **Determinism makes ingestion cheap.** Deterministic IDs + `MERGE` + a cached
  extraction step turn a re-ingest into a two-minute no-op.
- **Free-tier daily quotas are the real constraint.** Build the cache once; never
  iterate against live LLM APIs; design evals to be resumable.
- **Neo4j and pgvector** — modelling a domain as a labelled property graph,
  writing parameterised Cypher, and joining a graph store to a vector store on a
  shared key (`chunk_id`).
- **Report the negative result.** The benchmark was built to answer a question,
  and "no measurable win on this corpus" is a valid answer.

---

## Documentation

| Document | Contents |
|----------|----------|
| [`docs/SETUP.md`](./docs/SETUP.md) | detailed local setup and gotchas |
| [`docs/WALKTHROUGH.md`](./docs/WALKTHROUGH.md) | run every script and test, step by step, with expected output |
| [`docs/STRUCTURE.md`](./docs/STRUCTURE.md) | what every folder and file does |
| [`docs/BRIEF.md`](./docs/BRIEF.md) | the original project brief, annotated with what shipped |
| [`docs/results/FINDINGS.md`](./docs/results/FINDINGS.md) | benchmark analysis: where the graph wins and loses |
| [`docs/results/BENCHMARK_RESULTS.md`](./docs/results/BENCHMARK_RESULTS.md) | per-question graded results |
| [`docs/spec/architecture.md`](./docs/spec/architecture.md) | system design, data models, module responsibilities |
| [`docs/spec/PLAN.md`](./docs/spec/PLAN.md) | the five-step build plan |
| [`docs/spec/BUILD_LOG.md`](./docs/spec/BUILD_LOG.md) | file-by-file build log with rationale |
| [`docs/spec/prd.md`](./docs/spec/prd.md) · [`docs/spec/rules.md`](./docs/spec/rules.md) | the original requirements and coding rules |
| [`data/README.md`](./data/README.md) · [`data/ONTOLOGY.md`](./data/ONTOLOGY.md) | the corpus and its vocabulary |

---

## Contributing

This is a personal learning project and not actively seeking contributions, but
issues and suggestions are welcome. See [`CONTRIBUTING.md`](./CONTRIBUTING.md).

## Author

**Shaikh Rumman Fardeen**
[rummanfardeen4567@gmail.com](mailto:rummanfardeen4567@gmail.com)

## License

MIT — see [`LICENSE.md`](./LICENSE.md).

---

## Appendix

**Why "Meridian"?** The corpus is fabricated. It describes a fictional fintech so
that the benchmark questions have unambiguous gold answers and nothing depends on
real, changing systems.

**Graph size.** 43 entities, 222 relationships. The entity count sits just under
the planned 45–65 range because the corpus genuinely resolves to 43 distinct
nodes. The relationship count runs high because edges are keyed on
`source_chunk_id` for provenance, so a fact stated in three documents is three
edges (distinct `(source, type, target)` triples ≈ 130).

**Cost.** Ingestion and every benchmark run were done on free API tiers, total
spend $0. Embeddings are local. The one-time extraction is cached in
`cache/llm.db`.
