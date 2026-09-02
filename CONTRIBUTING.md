# Contributing

This is a personal learning project. It is not actively looking for
contributions, but bug reports, questions, and suggestions are welcome as issues.

If you do want to open a pull request:

## Setup

Follow [`SETUP.md`](./SETUP.md), then confirm the offline suite passes:

```bash
pytest -m "not llm and not neo4j and not pgvector"
ruff check .
```

## Conventions

The project follows [`rules.md`](./rules.md). The short version:

- Functions under 60 lines, modules under 300. Type hints and a docstring on
  every public function.
- No magic numbers — use a module-level constant.
- Provider clients (`ChatGroq`, `PGVector`, `Neo4jGraph`, …) are built only in
  `src/config.py` and `src/graph/client.py`. Everything else asks for a handle.
- All Cypher lives in `src/graph/queries.py` as named templates with parameters.
  No f-strings into queries. No model-authored Cypher. Never `GraphCypherQAChain`.
- Ingestion is deterministic and idempotent: deterministic IDs, `MERGE` not
  `CREATE`, re-running changes zero rows.
- Every entity carries `source_chunk_id`; every relationship also carries
  `evidence` (a real substring of its chunk).
- Test-first for resolution, extraction validation, routing, and citations.
  Smoke-test the plumbing.

## Tests

- Add a test module per source module.
- Mark tests that need external services: `@pytest.mark.llm`,
  `@pytest.mark.neo4j`, `@pytest.mark.pgvector`.
- Do not iterate against live LLM APIs — the free-tier daily quota is small.
  Cache-first, one shot.

## Commits

Small, focused commits. Run `ruff check .` and the offline suite before pushing.
