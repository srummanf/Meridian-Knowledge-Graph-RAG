# Routing Metrics

Router: `gpt-oss-20b` via `src/pipeline/router.py`. Eval set: `tests/fixtures/routing_eval.json` (21 questions).

**Accuracy: 95.2%** (gate ≥ 90%) — PASS

## Confusion matrix (gold → predicted)

| gold ↓ / pred → | VECTOR | GRAPH | HYBRID | REFUSE |
|---|---|---|---|---|
| **VECTOR** | 6 | 0 | 0 | 0 |
| **GRAPH** | 1 | 10 | 0 | 0 |
| **HYBRID** | 0 | 0 | 0 | 0 |
| **REFUSE** | 0 | 0 | 0 | 4 |

## Misclassifications

- `GRAPH` → `VECTOR` (conf 0.97): What does the Billing Service depend on?
