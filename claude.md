# Working with Claude Code on this project

**Version:** 3.0 · **Updated:** 2026-09-01

The spec is in `prd.md`, `architecture.md`, `rules.md`, `phases.md`; the corpus
contract is in `data/ONTOLOGY.md` and `data/SCHEMA.md`.

---

## 1. Split of responsibility

**You decide:** what to build next (from `phases.md`), architecture/ontology
changes, whether a gate is met, trade-offs.

**Claude does:** implementation, boilerplate, tests, debugging, refactors — one
component at a time, following `rules.md`.

---

## 2. Prompt shape

```
Phase: 3.1 — Router
File: src/pipeline/router.py

Task: LangGraph node that classifies a question into VECTOR/GRAPH/HYBRID/REFUSE.

Requirements:
- router_model().with_structured_output(RoutingDecision)
- few-shot: 3-4 examples per class, pulled from data/benchmark/questions.md
- confidence < 0.70 => HYBRID
- log question + route + confidence
- rules.md: function < 60 lines, type hints, docstring, named constants

Done when: tests/test_router.py hits >= 90% on the labelled set
Reference: architecture.md section 6 (hand-written), rules.md section 5.1
```

One file / one node per prompt. Reference the doc section, don't re-paste it.

---

## 3. Framework vs. hand-written

LangChain/LangGraph own the plumbing (loaders, splitters, model wrappers,
structured output, `PGVector`, `Neo4jGraph`). Claude should use them, not
reinvent them.

Hand-written (Claude implements, you defend in interviews):
`src/pipeline/router.py`, `src/pipeline/retrieve_graph.py` + `src/graph/queries.py`,
`src/pipeline/validate.py`, `src/ingest/resolve.py`.

**Never** `GraphCypherQAChain` — the model must not author Cypher against the DB.

---

## 4. Test-first where it's cheap

For resolution, extraction validation, citations, and routing: failing test
first, then make it pass. For plumbing (config, clients): build and smoke-test.

---

## 5. What not to ask Claude to decide

Ontology changes, whether F1 is good enough, the routing taxonomy, corpus
content. Claude can propose; you commit.

---

## 6. Debugging prompts

Give the exact error, what you expected, the phase, the relevant code. Ask for a
diagnosis before a fix.

---

## 7. Session hygiene

Start: "Phase X.Y, here's what's done, next file." End: files changed + next
task. Claude doesn't remember across sessions — the docs do, so when a decision
changes, update the relevant spec doc in the same session.

---

## 8. Constraints to restate when relevant

- Provider classes (`ChatGroq`, etc.) are built only in `src/config.py`.
- Cypher only via `src/graph/queries.py` templates, parameters not f-strings;
  never `GraphCypherQAChain`.
- Every entity/relationship carries `source_chunk_id` (+ `evidence` for edges).
- MERGE, never CREATE. Deterministic IDs.
- Embeddings local (`bge-small`, 384-dim). Vector search exact, no HNSW.
- Pydantic v2 API; extraction/routing via `with_structured_output`.
- The query pipeline is a LangGraph `StateGraph`.
