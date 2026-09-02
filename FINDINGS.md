# Findings — Graph RAG vs. Vector-only on the Meridian corpus

Raw run: `tests/fixtures/benchmark_run.json` · proposed grades + reading:
`BENCHMARK_RESULTS.md` · scorer: `python scripts/score_benchmark.py`.

**Scope:** 13 of the 30 benchmark questions were run (all of 1-hop, a slice of
2-hop, one each of 3-hop / aggregation / refusal). The free-tier daily quota does
not cover 30 × 2, and B18's plan call alone took 7.8 min under sustained
rate-limiting. The sample is small but the pattern is consistent and the two
failure modes below are structural, not sampling noise.

## Setup

Both systems share everything except routing: the same 42 chunks, the same local
`bge-small` embeddings, the same synthesis prompt, the same citation validator.
The **graph system** routes each question (VECTOR / GRAPH / HYBRID / REFUSE) and,
on a graph route, plans a query, runs a Cypher template, and turns the resulting
edges into sentences. The **vector-only baseline** (`src/baselines/vector_only.py`)
pins the router to VECTOR — the graph is never touched. Any category-level gap is
therefore attributable to graph traversal, not to a better prompt or better
chunks.

## Headline: the graph did not beat the baseline on this benchmark

| Category | Graph | Vector | Δ | Phase 5.2 gate | Met? |
|----------|------:|-------:|--:|----------------|------|
| 1-hop / definitional (B01–B08) | 0.94 | 0.94 | 0.00 | \|Δ\| ≤ 0.05 | **yes** |
| 2-hop (B09–B10) | 1.00 | 1.00 | 0.00 | Δ ≥ +0.15 | no |
| 3-hop (B17; B18 unpaired) | 0.75 | 0.75 | 0.00 | Δ ≥ +0.30 | no |
| aggregation (B24) | 1.00 | 1.00 | 0.00 | graph ≥ 0.80, vector ≤ 0.20 | no |
| refusal (B28) | 1.00 | 1.00 | — | — | — |

Two structural reasons, both worth stating plainly.

### 1. The corpus pre-aggregates its relationships

The Meridian docs are densely cross-referenced. Hub documents restate the
relationships that point at them:

- `databases/postgresql.md` has a "Usage at Meridian" section listing all five
  consuming services — **and** states the count, "5 services".
- `libraries/fastapi.md` lists its five consumers.
- `vulnerabilities/cve-2021-44228-log4shell.md` names the affected service.

So *"which services use PostgreSQL?"* (nominally a 2-hop traversal) and *"how
many services use PostgreSQL?"* (nominally an aggregation) are both answered by
vector search retrieving **one** document and reading the answer off it. On
B09, B10, B17, B24 the baseline returned the same entity set as the graph.

This is a property of *this* corpus. A corpus where each service doc states only
its own dependencies and nothing aggregates them would separate the systems on
2-hop questions too — the benchmark questions were written against an idealised
"facts are distributed" assumption the corpus does not hold to.

### 2. Template coverage is the graph retriever's ceiling

The graph retriever plans into one of six shapes (`neighbors`, `count`,
`two_constraint`, `path`, `blast_radius`, `lookup`). **B18** — *which teams own a
service that consumes an API owned by the Payments Team* — is a genuine 3-hop
chain: `team ─OWNS→ service ─CONSUMES→ api ─OWNED_BY→ team`. No shape expresses
it. The planner degraded to `neighbors` with a hallucinated `securitymechanism:jwt`
anchor and the graph returned nothing (score 0.0). The plan LLM call spent 7.8
minutes in rate-limit back-off getting there.

The graph's limit here is not multi-hop *reasoning* — the Cypher for that chain
is trivial — it is that a hand-written template set trades coverage for safety
(§ "Why not GraphCypherQAChain"), and the benchmark contains questions outside
that set.

## Where the graph still showed an edge

- **Citation quality (B10).** The graph cited each of the five service docs that
  states a `DEPENDS_ON FastAPI` edge; the baseline cited `libraries/fastapi.md`
  once. When a reader needs to verify per-entity, the graph's provenance is
  finer-grained.
- **Refusal routing (B28).** The graph classifies "is PostgreSQL better than
  MySQL" as REFUSE and never retrieves. The baseline retrieves PostgreSQL docs
  and relies on the synthesis prompt's "if the context does not answer, say so"
  guard to decline. Both produced a correct non-answer here, but the graph's is a
  hard guarantee and the baseline's is prompt-dependent.
- **Deterministic completeness (not isolated on this sample, but structural).**
  The graph returns exactly the set satisfying the query. Vector returns top-k;
  if the k-th relevant chunk ranks k+1 an entity is dropped and the answer still
  looks complete. On B09/B10 both happened to return all five — with `k=5` and
  five relevant chunks, one drop would have been invisible.

## Where the graph loses or costs more

- **Citation attribution quirk.** All five `service USES PostgreSQL` edges were
  extracted from `vulnerabilities/cve-2024-0985-postgresql.md` (that doc happens
  to enumerate the affected services), so on B09/B24 the graph cites the CVE doc
  for "the Auth Service uses PostgreSQL" while the baseline cites
  `databases/postgresql.md`. This is an extraction-quality artifact — Phase 1.5
  (a labelled extraction eval) would catch and fix it — not a property of graph
  retrieval.
- **Latency.** The graph route adds a plan LLM call and a Cypher round-trip. Warm
  and cached: GRAPH ~7–9 s vs. VECTOR ~3–5 s (`benchmark_run.json`). Cold, under
  free-tier throttling, the plan call can run for minutes (B18: 7.8 min).
- **Build cost.** Every graph fact is one LLM extraction, done up front and
  cached. The vector index needs no LLM at all.

## Cost & latency honesty

- Ingestion is one-time and cached; rebuilding both indexes from `cache/llm.db`
  is ~2 min, $0.
- Per query, warm: VECTOR ~3–5 s, GRAPH ~7–9 s, HYBRID ~8–9 s on Groq's free
  tier — dominated by the synthesis call, not retrieval. A paid tier or a local
  model puts this under the 3 s soft target.
- Free-tier **daily** quotas (Groq ~200 K tokens; Gemini ~20 requests) are the
  binding constraint and the reason the benchmark ran in small resumable subsets.

## Why not `GraphCypherQAChain`

The model never authors Cypher against the database. It fills a typed
`GraphQueryPlan` (which entity, which edge, which direction); the retriever maps
that to one of seven reviewed, parameterised templates. This is a security
control — no query injection, no accidental `DETACH DELETE` — and it makes
results reproducible: the same plan always runs the same Cypher. B18 is the cost
of that choice made visible.

## What this says about when to reach for a knowledge graph

- **A graph earns its keep when facts are genuinely distributed** — no document
  aggregates them, and the answer requires joining across sources. The Meridian
  corpus, as written, mostly pre-joins, so the graph's accuracy advantage did not
  materialise.
- **A graph is worth it for guarantees vector retrieval cannot give**: exact-set
  completeness, deterministic aggregation, and a refusal decision made before
  retrieval rather than delegated to a prompt.
- **A hand-written template retriever needs its template set matched to the
  question distribution.** Six shapes covered 12 of 13 here; the 13th needed a
  shape nobody wrote.

## How this would productionise

- **Extraction eval as a CI gate** (Phase 1.5) — would have caught the
  PostgreSQL-citation quirk before it reached the benchmark.
- **Widen the benchmark and/or the corpus** so multi-hop questions actually
  require multi-hop — the current corpus can't discriminate the two systems.
- **A `chain` template** (bounded variable-length path with typed endpoints)
  would cover B18-shaped questions without handing Cypher to the model.
- **HNSW** once the corpus is 10⁴+ vectors (irrelevant at 42; exact scan is
  sub-ms and recall-1.0).
- **A paid LLM tier** with a per-request token budget — removes the free-tier
  latency floor and lets the full 30-question benchmark run in one pass.
