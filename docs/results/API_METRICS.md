# API Metrics

Snapshot of one warm run of `tests/test_api.py::test_api_gate`. Soft latency
target: 3000 ms.

| Question | Route | Status | Latency (ms) |
|----------|-------|--------|--------------|
| What is the Auth Service? | VECTOR | 200 | 5088 |
| Which services use PostgreSQL? | GRAPH | 200 | 7564 |
| What is the Ledger API and which services consume it? | HYBRID | 200 | 8490 |
| Should the Payments Team rewrite the Ledger Service in Go? | REFUSE | 422 | 0 |

- answered requests: 3
- min / max latency: 5088 / 8490 ms
- p95 latency: 8490 ms  (target < 3000 ms, soft)

> Steady-state wall-clock: the pipeline is warmed once (embedding model, Neo4j driver, LangGraph compile) and the LLM cache is warm, so these numbers are Cypher + local embedding + merge/validate/synthesis-parse overhead, not API round-trips. Cold start adds ~25 s (HF Hub model check) and a cold Groq free-tier call adds 5–120 s of rate-limit back-off — neither is representative of a running server.
