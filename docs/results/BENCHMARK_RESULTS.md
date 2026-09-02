# Benchmark Results — Graph RAG vs. Vector-only

Raw run: `tests/fixtures/benchmark_run.json`. Rubric: `data/benchmark/questions.md`
(0 / 0.25 / 0.5 / 0.75 / 1.0). Scores below are **final** (graded by comparison to
the gold answer); `python scripts/score_benchmark.py` recomputes the reading.

**14 questions** — the set was scoped to what a single $0 free-tier run can
finish (`data/benchmark/questions.md` § Scope). B18's plan call alone took
7.8 min; its vector arm was not run before live benchmarking stopped.

| ID | Cat | Question | Gold route | Graph route | G | V | Notes |
|----|-----|----------|-----------|-------------|---|---|-------|
| B01 | 1-hop | What is the Auth Service? | VECTOR | VECTOR | 0.75 | 0.75 | identical (graph routed VECTOR); correct core, but dumps aliases + version + owner as noise |
| B02 | 1-hop | What is Kafka used for at Meridian? | VECTOR | VECTOR | 1.0 | 1.0 | identical; correct, names the consuming services |
| B03 | 1-hop | Which language is the Ledger Service written in? | VECTOR | VECTOR | 0.75 | 0.75 | "Java" not "Java 17"; identical |
| B04 | 1-hop | What does CVE-2021-44228 (Log4Shell) do? | VECTOR | VECTOR | 0.75 | 0.75 | correct mechanism, omits the affected version range; identical |
| B05 | 1-hop | What is mTLS and where is it used at Meridian? | VECTOR | VECTOR | 1.0 | 1.0 | correct, names Auth/Ledger/User API |
| B06 | 1-hop | What database does the Fraud Service use as a feature store? | VECTOR | VECTOR | 0.75 | 0.75 | "Elasticsearch" — right, but bare (no "for feature lookups" context) |
| B07 | 1-hop | Which team owns the Merchant Dashboard? | VECTOR | VECTOR | 1.0 | 1.0 | "Growth Team" |
| B08 | 1-hop | What protocol does the Public REST API use? | VECTOR | VECTOR | 0.75 | 0.75 | "REST" — omits the HTTP/JSON detail gold gives |
| B09 | 2-hop | Which services use PostgreSQL? | GRAPH | GRAPH | 1.0 | 1.0 | both list the correct 5; **graph cites the CVE doc** (extraction quirk), vector cites postgresql.md |
| B10 | 2-hop | Which services depend on FastAPI? | GRAPH | GRAPH | 1.0 | 1.0 | both correct 5; **graph has per-service citations**, vector cites fastapi.md |
| B17 | 3-hop | If Log4Shell is exploited, which Meridian products are affected? | GRAPH | GRAPH | 0.75 | 0.75 | both name Payments Platform (correct) but also include Ledger Service (the intermediate hop, not a product) |
| B18 | 3-hop | Which teams own a service that consumes an API owned by the Payments Team? | GRAPH | GRAPH | 0.0 |  | **graph failed** — planner hallucinated a `jwt` anchor, no template expresses the 3-hop chain; 7.8 min. Vector arm not run. |
| B24 | aggregation | How many services use PostgreSQL? | GRAPH | GRAPH | 1.0 | 1.0 | both "5"; count is pre-stated in `databases/postgresql.md`, so vector doesn't need to aggregate |
| B28 | refusal | Is PostgreSQL better than MySQL for Meridian? | REFUSE | REFUSE | 1.0 | 1.0 | graph REFUSEs at the router; vector retrieves then declines via the synthesis guard |

## Reading

| Category | Graph | Vector | Δ | Gate | Met? |
|----------|------:|-------:|--:|------|------|
| 1-hop (B01–B08) | 0.84 | 0.84 | 0.00 | \|Δ\| ≤ 0.05 | **yes** |
| 2-hop (B09–B10) | 1.00 | 1.00 | 0.00 | Δ ≥ +0.15 | no |
| 3-hop (B17; B18 graph-only) | 0.75 | 0.75 | 0.00 | Δ ≥ +0.30 | no |
| aggregation (B24) | 1.00 | 1.00 | 0.00 | graph ≥ 0.80, vector ≤ 0.20 | no (vector = 1.00) |
| refusal (B28) | 1.00 | 1.00 | — | — | — |

**The gate is not met on this sample.** Two causes, both real and
both worth writing up (see `FINDINGS.md`):

1. **The corpus pre-aggregates.** `databases/postgresql.md` lists its five
   consumers; `libraries/fastapi.md` lists its consumers; `databases/postgresql.md`
   states the count "5". Vector retrieves one hub doc and reads the answer off it,
   so "2-hop" and "aggregation" questions never actually force a traversal.
2. **Template coverage is the graph's ceiling.** B18 needs
   team→OWNS→service→CONSUMES→api→OWNED_BY→team. None of the six `GraphQueryPlan`
   shapes express it; the planner degraded to `neighbors` with a hallucinated
   anchor.

Where the graph still shows an edge on this sample: **citation quality on B10**
(per-service sources vs. one hub doc) and **refusal routing on B28** (declines
before retrieving). Neither is a scored-accuracy win.

## Per-question detail

### B01 (1-hop) — What is the Auth Service?
**Gold:** Meridian's identity provider. It registers users, verifies credentials, and issues JWT access tokens via the OAuth2 authorization-code flow.
**Gold sources:** services/auth-service.md#overview

**graph** (VECTOR, 35447 ms, ~1014 tok): The Auth Service is a Service (aliases: authn‑svc, Authentication Service, the auth svc) owned by the Platform Team, version 5.4. It is Meridian’s identity provider that registers users, verifies credentials, and issues JWT access tokens via the OAuth2 authorization‑code flow. It implements OAuth2 and is itself the OAuth2 provider for Meridian.
  citations: ['services/auth-service.md', 'services/auth-service.md', 'services/auth-service.md']

**vector** (VECTOR, 2802 ms, ~1014 tok): The Auth Service is a Service (aliases: authn‑svc, Authentication Service, the auth svc) owned by the Platform Team, version 5.4. It is Meridian’s identity provider that registers users, verifies credentials, and issues JWT access tokens via the OAuth2 authorization‑code flow. It implements OAuth2 and is itself the OAuth2 provider for Meridian.
  citations: ['services/auth-service.md', 'services/auth-service.md', 'services/auth-service.md']

### B02 (1-hop) — What is Kafka used for at Meridian?
**Gold:** Event streaming. The Ledger Service publishes a transaction event to Kafka for every posted journal entry; downstream services consume that stream.
**Gold sources:** databases/kafka.md#overview

**graph** (VECTOR, 7657 ms, ~1017 tok): Kafka is Meridian’s event streaming platform; the Ledger Service publishes transaction events to Kafka and the Notification and Fraud services consume those transaction events.
  citations: ['databases/kafka.md']

**vector** (VECTOR, 2575 ms, ~1017 tok): Kafka is Meridian’s event streaming platform; the Ledger Service publishes transaction events to Kafka and the Notification and Fraud services consume those transaction events.
  citations: ['databases/kafka.md']

### B03 (1-hop) — Which language is the Ledger Service written in?
**Gold:** Java 17. It is the only Java service at Meridian; every other service is Python 3.11.
**Gold sources:** services/ledger-service.md#dependencies, libraries/java.md#overview

**graph** (VECTOR, 20820 ms, ~739 tok): The Ledger Service is written in Java.
  citations: ['libraries/java.md']

**vector** (VECTOR, 2685 ms, ~739 tok): The Ledger Service is written in Java.
  citations: ['libraries/java.md']

### B04 (1-hop) — What does CVE-2021-44228 (Log4Shell) do?
**Gold:** A critical RCE in Apache Log4j; a crafted string in logged input causes remote code execution via JNDI. Affects Log4j 2.0-beta9 through 2.14.1.
**Gold sources:** vulnerabilities/cve-2021-44228-log4shell.md

**graph** (VECTOR, 12288 ms, ~1200 tok): CVE-2021-44228 (Log4Shell) is a critical remote‑code‑execution vulnerability in Apache Log4j that allows a crafted string in logged input to cause Log4j to load and execute remote code via JNDI.
  citations: ['vulnerabilities/cve-2021-44228-log4shell.md']

**vector** (VECTOR, 2457 ms, ~1200 tok): CVE-2021-44228 (Log4Shell) is a critical remote‑code‑execution vulnerability in Apache Log4j that allows a crafted string in logged input to cause Log4j to load and execute remote code via JNDI.
  citations: ['vulnerabilities/cve-2021-44228-log4shell.md']

### B05 (1-hop) — What is mTLS and where is it used at Meridian?
**Gold:** Mutual TLS — both sides present a certificate. Used to secure internal gRPC APIs: the Auth API, Ledger API, and User API.
**Gold sources:** security/mtls.md

**graph** (VECTOR, 8146 ms, ~751 tok): mTLS is mutual TLS where both sides of a connection present a certificate. Meridian uses it so that only known services can call internal gRPC APIs. It secures the Auth API, the Ledger API, and the User API for internal traffic, and every internal gRPC endpoint is secured by mTLS.
  citations: ['security/mtls.md', 'security/mtls.md', 'security/mtls.md', 'security/mtls.md', 'security/mtls.md', 'protocols/grpc.md']

**vector** (VECTOR, 2806 ms, ~751 tok): mTLS is mutual TLS where both sides of a connection present a certificate. Meridian uses it so that only known services can call internal gRPC APIs. It secures the Auth API, the Ledger API, and the User API for internal traffic, and every internal gRPC endpoint is secured by mTLS.
  citations: ['security/mtls.md', 'security/mtls.md', 'security/mtls.md', 'security/mtls.md', 'security/mtls.md', 'protocols/grpc.md']

### B06 (1-hop) — What database does the Fraud Service use as a feature store?
**Gold:** Elasticsearch, for historical feature lookups during scoring.
**Gold sources:** services/fraud-service.md#data--storage

**graph** (VECTOR, 15780 ms, ~1243 tok): Elasticsearch
  citations: ['services/fraud-service.md']

**vector** (VECTOR, 2678 ms, ~1243 tok): Elasticsearch
  citations: ['services/fraud-service.md']

### B07 (1-hop) — Which team owns the Merchant Dashboard?
**Gold:** The Growth Team.
**Gold sources:** products/merchant-dashboard.md#ownership, teams/growth-team.md#ownership

**graph** (VECTOR, 40794 ms, ~1111 tok): Growth Team
  citations: ['products/merchant-dashboard.md']

**vector** (VECTOR, 2762 ms, ~1111 tok): Growth Team
  citations: ['products/merchant-dashboard.md']

### B08 (1-hop) — What protocol does the Public REST API use?
**Gold:** REST (HTTP/JSON) as its primary protocol.
**Gold sources:** services/api-gateway.md#apis, protocols/rest.md --- ## Category 2 — Two-hop (Graph advantage begins)

**graph** (VECTOR, 12925 ms, ~747 tok): The Public REST API uses the REST protocol.
  citations: ['services/api-gateway.md#overview']

**vector** (VECTOR, 2772 ms, ~747 tok): The Public REST API uses the REST protocol.
  citations: ['services/api-gateway.md#overview']

### B09 (2-hop) — Which services use PostgreSQL?
**Gold:** Auth Service, User Service, Billing Service, Ledger Service, Reporting Service (5).
**Gold sources:** databases/postgresql.md#usage-at-meridian

**graph** (GRAPH, 8726 ms, ~134 tok): Auth Service, Billing Service, Ledger Service, Reporting Service, and User Service use PostgreSQL.
  citations: ['vulnerabilities/cve-2024-0985-postgresql.md', 'vulnerabilities/cve-2024-0985-postgresql.md', 'vulnerabilities/cve-2024-0985-postgresql.md', 'vulnerabilities/cve-2024-0985-postgresql.md', 'vulnerabilities/cve-2024-0985-postgresql.md']

**vector** (VECTOR, 4334 ms, ~1078 tok): Auth Service, User Service, Billing Service, Ledger Service, and Reporting Service use PostgreSQL.
  citations: ['databases/postgresql.md', 'vulnerabilities/cve-2024-0985-postgresql.md']

### B10 (2-hop) — Which services depend on FastAPI?
**Gold:** API Gateway, User Service, Notification Service, Fraud Service, Reporting Service (5).
**Gold sources:** libraries/fastapi.md#usage-at-meridian

**graph** (GRAPH, 8760 ms, ~127 tok): API Gateway, Fraud Service, Notification Service, Reporting Service, and User Service depend on FastAPI.
  citations: ['services/api-gateway.md#overview', 'services/fraud-service.md', 'services/notification-service.md', 'services/reporting-service.md#overview', 'services/user-service.md#overview']

**vector** (VECTOR, 10857 ms, ~1181 tok): API Gateway, User Service, Notification Service, Fraud Service, and Reporting Service depend on FastAPI.
  citations: ['libraries/fastapi.md', 'services/user-service.md#overview', 'libraries/fastapi.md', 'libraries/fastapi.md', 'libraries/fastapi.md']

### B17 (3-hop) — If Log4Shell is exploited, which Meridian products are affected?
**Gold:** The Payments Platform. Chain: CVE-2021-44228 → affects Log4j 2.13.0 → the Ledger Service depends on it → the Ledger Service is part of the Payments Platform.
**Gold sources:** vulnerabilities/cve-2021-44228-log4shell.md, libraries/log4j.md, services/ledger-service.md

**graph** (GRAPH, 8670 ms, ~115 tok): Ledger Service and Payments Platform are affected.
  citations: ['libraries/log4j.md', 'libraries/log4j.md']

**vector** (VECTOR, 30710 ms, ~980 tok): The Ledger Service and, by extension, the Payments Platform are affected if Log4Shell is exploited.
  citations: ['vulnerabilities/cve-2021-44228-log4shell.md', 'libraries/log4j.md']

### B24 (aggregation) — How many services use PostgreSQL?
**Gold:** 5.
**Gold sources:** databases/postgresql.md

**graph** (GRAPH, 7773 ms, ~136 tok): 5 services use PostgreSQL.
  citations: ['vulnerabilities/cve-2024-0985-postgresql.md']

**vector** (VECTOR, 3999 ms, ~1061 tok): 5 services use PostgreSQL.
  citations: ['databases/postgresql.md']

### B28 (refusal) — Is PostgreSQL better than MySQL for Meridian?
**Gold:** Opinion / not answerable from the corpus. The corpus states Meridian chose PostgreSQL for strong consistency and its NUMERIC type, but makes no comparative judgement against MySQL.
**Gold sources:** —

**graph** (REFUSE, 2949 ms, ~11 tok): (refused)
  citations: —
  notes: ['refused: nothing retrieved for the question']

**vector** (VECTOR, 3735 ms, ~1010 tok): The retrieved context does not contain enough information to answer this question.
  citations: —

### B18 (3-hop) — Which teams own a service that consumes an API owned by the Payments Team?
**Gold:** The Data Team (Fraud Service and Reporting Service consume the Ledger API; Reporting also consumes the Billing API) and the Payments Team itself (Billing consumes the Ledger API). The Ledger API and Billing API are owned by the Payments Team.
**Gold sources:** services/{fraud, teams/*.md

**graph** (GRAPH, 467385 ms, ~72 tok): The retrieved context does not contain enough information to answer this question.
  citations: —

