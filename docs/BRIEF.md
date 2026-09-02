# Project brief and completion status

The original brief this project was built against, annotated with what actually
shipped. Full analysis of the outcome is in
[`results/FINDINGS.md`](./results/FINDINGS.md). The repo groups its own build into
five steps slightly differently — see [`spec/PLAN.md`](./spec/PLAN.md).

Legend: `[x]` done · `[~]` done differently, with a caveat · `[ ]` not done.

---

## Knowledge Graph RAG for Enterprise Data

**Brief's stack:** Python · Neo4j · LangChain · Claude API · pgvector · FastAPI
**As built:** Python 3.11 · Neo4j 5 Community · LangChain + **LangGraph** ·
**Groq `gpt-oss-120b` / `gpt-oss-20b` with Google Gemini fallback** (both free
tier — Claude API was not used) · pgvector (Postgres 16) · FastAPI + Uvicorn ·
local `bge-small` embeddings · pytest · ruff · Docker Compose

**Estimated build time:** 3–4 weeks part time.

### Why this project signals

Almost every candidate has built vector RAG. Very few have built retrieval that
answers questions requiring two or three hops across related entities. This
project proves you understand where embeddings fail and what to do about it.

> **What this build actually proved:** on a corpus whose documents pre-aggregate
> their own relationships, plain vector RAG *matches* the graph on multi-hop
> questions. The graph's real value is elsewhere — citation precision, refusal
> handling, exact-set completeness, and questions no single document answers.
> That negative result, measured and reported, is the artifact.

---

## Step 1 — Extract entities and relationships into Neo4j

- `[x]` **Corpus with real relationships.** *Meridian*, a fabricated fintech
  architecture wiki (37 docs): services, APIs, libraries, datastores, teams, two
  CVEs. Dependency chains and a CVE → library → service → product blast radius.
- `[x]` **Constrained ontology, defined before any code.** 11 entity types, 12
  relationship types, fixed in `data/ONTOLOGY.md` (slightly over the brief's
  5–10 / 8–15, deliberately).
- `[x]` **Chunk + strict-schema extraction pass.** `chat_model.with_structured_output(ExtractionResult)`
  returning `{entity type, canonical name, relationship type, source_chunk_id,
  confidence, evidence}`. Groq needs `method="json_schema"`. Every response is
  validated (enum, evidence is a real substring, allowed properties, endpoints
  exist) and failures retry ≤3 with the errors fed back.
- `[~]` **Entity resolution.** Done via a **hand-authored alias table** +
  name normalisation + deterministic IDs + merge-on-id — not embedding-similarity
  clustering with a tuned threshold. Works here because the corpus is small and
  its aliases are known; the brief's approach is the right one at real scale.
- `[x]` **`MERGE` not `CREATE`, idempotent.** Deterministic IDs; re-running the
  ingest changes zero rows. Every edge carries `source_chunk_id` **and**
  `evidence` (the exact sentence).
- `[x]` **Cost budgeted and cached.** LLM calls cached in `cache/llm.db`
  (LangChain `SQLiteCache`, keyed on the full prompt = chunk content). Total
  extraction spend: **$0**, on the Groq/Gemini free tiers. A full rebuild from
  cache is ~2 minutes.
- `[ ]` **Extraction eval** (precision/recall/F1 on the benchmark-critical
  relationships). Planned but not built. Left as roadmap — it would
  catch the known bug where every `USES PostgreSQL` edge is attributed to the CVE
  document.

**Status: complete, with a simpler entity-resolution approach and no formal
extraction eval.**

---

## Step 2 — Build the vector index alongside the graph

- `[x]` **Same chunks embedded into pgvector** with metadata `{chunk_id,
  document, entity_ids}`. Embeddings are local (`bge-small`, 384-dim) — no API
  call.
- `[x]` **Shared `chunk_id` across both stores.** The join key. A graph fact and
  a retrieved passage both carry it, so synthesis and the citation validator
  work across the two sources.
- `[~]` **HNSW + `ef_search` tuning.** Deliberately **not** done. The corpus is
  ~42 vectors; an exact cosine scan is sub-millisecond and recall-1.0 by
  construction. HNSW/IVFFlat only pay off 3–5 orders of magnitude larger and
  would add approximation error. The reasoning is documented and gated by a
  recall test.
- `[x]` **Recall@k on a labelled set, before the router.** 12
  `(question → gold chunk)` pairs; **recall@1 = 1.00**.

**Status: complete. Exact scan instead of an ANN index, with the justification
written up.**

---

## Step 3 — Route questions to the right retrieval path

- `[x]` **Cheap router.** One `gpt-oss-20b` call with a 12-example few-shot
  prompt returning `VECTOR` / `GRAPH` / `HYBRID` / `REFUSE`; a
  `confidence < 0.70` fallback downgrades to `HYBRID` (run both, merge).
  **95.2%** accurate on 21 labelled questions disjoint from the few-shot.
- `[x]` **Routing policy.** Graph for connection / multi-hop / aggregation /
  "which Xs"; vector for definitions and single-fact lookups; REFUSE for opinion,
  forecast, and out-of-domain.
- `[x]` **Parameterised Cypher only.** The model fills a typed `GraphQueryPlan`
  (which entity, which edge, which direction, what shape). The code resolves the
  anchors and picks one of **seven reviewed templates** (six query shapes). The
  model never emits Cypher against the database — a security control and a
  reproducibility control. `GraphCypherQAChain` is explicitly not used.
- `[x]` **Every routing decision logged** (`question → route conf`), which fed
  the benchmark.

**Status: complete.**

---

## Step 4 — Merge both sources into one grounded answer

- `[x]` **Paths → readable statements.** Each edge is rendered with a
  per-relationship-type verb ("Auth Service uses PostgreSQL.") before it reaches
  the prompt — no raw triples.
- `[x]` **Dedupe + labelled context.** Passages deduped to best-score per
  `chunk_id` then near-duplicate text; facts deduped by sentence. Assembled under
  explicit `GRAPH FACTS` / `RETRIEVED PASSAGES` headers.
- `[x]` **Citation per claim, validated.** Synthesis emits a `{claim, chunk_id,
  source_type}` per claim. The validator checks every `chunk_id` is in the
  retrieved set; on a miss it regenerates once with a `Cite ONLY from: […]`
  allow-list and drops any leftover bad citation with a note. **100%
  cited-source validity** on the sample; an injected fake citation is caught.

**Status: complete.**

---

## Step 5 — Benchmark against plain vector RAG and publish the delta

- `[~]` **Stratified question set.** 30 questions were written (1-hop, 2-hop,
  3-hop, aggregation, refusal), then **cut to 14** — what a single $0 free-tier
  run completes. Below the brief's 50–100.
- `[x]` **Both systems on the same set, accuracy by hop count.** The baseline
  (`src/baselines/vector_only.py`) is the identical pipeline with the router
  pinned to `VECTOR`.
- `[~]` **The expected curve did not appear.** Parity on every category
  (Δ ≈ 0.00), not a widening gap. Two structural causes: the corpus pre-lists its
  relationships, and one true 3-hop question exceeded the template set. This is
  written up honestly rather than hidden.
- `[x]` **Latency and cost reported.** Per-query warm latency (VECTOR ~5 s, GRAPH
  ~7–9 s on the free tier), the one-time ~2-minute cached ingestion, and the $0
  total. Being explicit that the graph is slower and more expensive to build is
  what would make an accuracy claim credible — here there is no accuracy claim to
  make.
- `[x]` **Benchmark table at the top of the README**, above the architecture.

**Status: complete. The result is a measured parity, not a win — reported as the
finding.**

---

## Done when

- `[x]` A FastAPI endpoint (`POST /query`) answers questions with validated
  citations.
- `[x]` The README opens with a benchmark table comparing the system to a
  vector-only baseline by hop count.

---

## Where this usually goes wrong — and how it went here

- `[x]` **Open-ended ontology** → avoided. 11 + 12 types, fixed before coding.
- `[~]` **Skipping entity resolution** → not skipped, but done with an alias
  table rather than embedding clustering.
- `[x]` **Model writes raw Cypher** → avoided. Typed plan → fixed templates.
- `[~]` **Corpus with no real relationships** → the corpus *has* relationships,
  but it is so densely cross-referenced that vector search reaches the same
  answers. The "graph is pointless" failure mode partly materialised — for a
  different reason than the brief warns about.

---

## Stretch goals

- `[ ]` Incremental graph updates instead of full re-ingestion.
- `[ ]` Community detection for corpus-level summaries.
- `[ ]` Graph visualisation in the response UI.
