# Meridian Knowledge Graph RAG

Hybrid **knowledge-graph + vector RAG** over a 37-document technical corpus
(*Meridian*, a fictional fintech). Routes each question to graph traversal or
vector search, merges the results, and answers with validated citations.

> **Status:** end to end. `POST /query` runs route → graph/vector retrieval →
> merge → cited synthesis → citation validation, 100% citation validity on the
> sample. Corpus fully loaded: 42/42 chunks → 43 entities / 222 relationships,
> 42 vectors. Router 95.2%; vector recall@1 = 1.00.

## Benchmark — Graph RAG vs. vector-only (partial, 13/30 questions)

Same pipeline, router pinned to VECTOR for the baseline — the graph is the only
variable. Proposed grades; full write-up in [`FINDINGS.md`](./FINDINGS.md).

| Category | Graph | Vector | Δ |
|----------|------:|-------:|--:|
| 1-hop / definitional | 0.94 | 0.94 | 0.00 |
| 2-hop | 1.00 | 1.00 | 0.00 |
| 3-hop | 0.75 | 0.75 | 0.00 |
| aggregation | 1.00 | 1.00 | 0.00 |
| refusal | 1.00 | 1.00 | — |

**The graph did not beat the baseline on accuracy** — the Meridian corpus is
densely cross-referenced (hub docs list their own consumers and state counts), so
vector retrieval answers nominal multi-hop questions from a single document. The
one question needing a genuine 3-hop chain (B18) exposed the retriever's other
limit: none of its six query-plan templates express it. Where the graph still
wins: finer-grained citations, refusal decided before retrieval, and exact-set
completeness guarantees. See [`FINDINGS.md`](./FINDINGS.md).

## Progress

| Phase | State | Output |
|-------|-------|--------|
| 0 — Setup | ✅ | DBs + LLM providers reachable, `check_setup.py` PASS |
| 1.1 — Models | ✅ | `src/models/*` — typed vocabulary & pipeline shapes (35 tests) |
| 1.2 — Chunking | ✅ | `src/ingest/chunk.py` — 37 docs → 42 chunks (15 tests) |
| 1.3 — Extraction | ✅ | `src/ingest/extract.py` + `src/utils/errors.py` — LLM → validated `ExtractionResult` (24 tests) |
| 1.4 — Graph load + resolution | ✅ | 42/42 chunks in Neo4j (43 entities, 222 rels), idempotent & $0 to rebuild from cache |
| 1.5 — Extraction eval | ⬜ | F1 ≥ 0.85 / 0.75 |
| 2.1 — Embed + store | ✅ | `src/ingest/load_vector.py` — 42 chunks → local `bge-small` (384-dim) → pgvector, keyed on `chunk_id` (6 tests) |
| 2.2 — Recall check | ✅ | `scripts/eval_vector.py` + `vector_eval.json` — recall@1 = 1.00 over 12 questions (2 tests) |
| 3.1 — Router | ✅ | `src/pipeline/router.py` — question → VECTOR/GRAPH/HYBRID/REFUSE, 95.2% on 21 labelled (`ROUTING_METRICS.md`, 9 tests) |
| 3.2 — Graph retriever | ✅ | `src/pipeline/retrieve_graph.py` + 7 read templates in `src/graph/queries.py` — plan LLM → resolve → Cypher → sentences; B09/B14/B16/B17/B24 exact, ≤56 ms (11 tests) |
| 3.3 — Vector retriever | ✅ | `src/pipeline/retrieve_vector.py` — exact cosine top-k; B01–B08 all rank 1 (`scripts/eval_vector_retrieval.py`, 7 tests) |
| 3.4 — Merge + pipeline | ✅ | `src/pipeline/{merge,graph}.py` — dedupe + labelled context; LangGraph `StateGraph` with graph→vector→REFUSE fallbacks (21 tests) |
| 4.1 — Synthesize | ✅ | `src/pipeline/synthesize.py` — labelled context → cited answer, citation per claim; 5/5 sample answers coherent + fully cited (4 tests) |
| 4.2 — Validate citations | ✅ | `src/pipeline/validate.py` + `compile_answer_pipeline` — every cited chunk_id ∈ retrieved set, one allow-listed regeneration; injected bad citation caught (8 tests) |
| 4.3 — API + end to end | ✅ | `src/api/{main,schemas,dependencies}.py` — `POST /query` (200 / 422 out-of-scope / 400 / 503), `GET /health`; one integration test per route (`API_METRICS.md`, 9 tests) |
| 5.1 — Baseline + harness | ✅ | `src/baselines/vector_only.py`, `scripts/benchmark.py` (resumable), `scripts/score_benchmark.py` (7 tests) |
| 5.2 — Grade + analyse | 🚧 | 13/30 run; proposed grades in `BENCHMARK_RESULTS.md`; gate not met on this sample |
| 5.3 — Writeup | 🚧 | `FINDINGS.md` drafted, `SETUP.md` done, README table above |

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
