# Benchmark Questions — Meridian Knowledge Graph

13 questions for the Phase 5 comparison of Graph RAG vs. vector-only RAG,
stratified by hop count. Each has a gold answer grounded in the corpus and the
route it *should* take.

> **Scope.** This started as a 30-question set. It was cut to the 13 that a
> single free-tier ($0) benchmark run could complete — all of Category 1, a
> slice of each other category, enough to see the pattern. The original IDs
> (B01–B10, B17, B18, B24, B28) are kept so they map to the code and fixtures.
> `scripts/benchmark.py` converts this file to
> `tests/fixtures/benchmark_questions.json`.

## Grading rubric (manual, per answer)

| Score | Meaning |
|-------|---------|
| 1.0  | All entities/relationships correct, complete, citations valid (a correct REFUSE = 1.0) |
| 0.75 | Core correct, minor omission or extra |
| 0.5  | Partially correct, missing key entities |
| 0.25 | Mostly wrong |
| 0.0  | Wrong, hallucinated, or failed to answer |

---

## Category 1 — Single-hop / definitional (expect ~parity)

**B01. What is the Auth Service?**
Route: VECTOR
Gold: Meridian's identity provider. It registers users, verifies credentials, and
issues JWT access tokens via the OAuth2 authorization-code flow.
Sources: services/auth-service.md#overview

**B02. What is Kafka used for at Meridian?**
Route: VECTOR
Gold: Event streaming. The Ledger Service publishes a transaction event to Kafka
for every posted journal entry; downstream services consume that stream.
Sources: databases/kafka.md#overview

**B03. Which language is the Ledger Service written in?**
Route: VECTOR
Gold: Java 17. It is the only Java service at Meridian; every other service is
Python 3.11.
Sources: services/ledger-service.md#dependencies, libraries/java.md#overview

**B04. What does CVE-2021-44228 (Log4Shell) do?**
Route: VECTOR
Gold: A critical RCE in Apache Log4j; a crafted string in logged input causes
remote code execution via JNDI. Affects Log4j 2.0-beta9 through 2.14.1.
Sources: vulnerabilities/cve-2021-44228-log4shell.md

**B05. What is mTLS and where is it used at Meridian?**
Route: VECTOR
Gold: Mutual TLS — both sides present a certificate. Used to secure internal gRPC
APIs: the Auth API, Ledger API, and User API.
Sources: security/mtls.md

**B06. What database does the Fraud Service use as a feature store?**
Route: VECTOR
Gold: Elasticsearch, for historical feature lookups during scoring.
Sources: services/fraud-service.md#data--storage

**B07. Which team owns the Merchant Dashboard?**
Route: VECTOR
Gold: The Growth Team.
Sources: products/merchant-dashboard.md#ownership, teams/growth-team.md#ownership

**B08. What protocol does the Public REST API use?**
Route: VECTOR
Gold: REST (HTTP/JSON) as its primary protocol.
Sources: services/api-gateway.md#apis, protocols/rest.md

---

## Category 2 — Two-hop (Graph advantage begins)

**B09. Which services use PostgreSQL?**
Route: GRAPH
Gold: Auth Service, User Service, Billing Service, Ledger Service, Reporting
Service (5).
Sources: databases/postgresql.md#usage-at-meridian + each service doc

**B10. Which services depend on FastAPI?**
Route: GRAPH
Gold: API Gateway, User Service, Notification Service, Fraud Service, Reporting
Service (5).
Sources: libraries/fastapi.md#usage-at-meridian

---

## Category 3 — Three-hop and multi-constraint (wide gap expected)

**B17. If Log4Shell is exploited, which Meridian products are affected?**
Route: GRAPH
Gold: The Payments Platform. Chain: CVE-2021-44228 → affects Log4j 2.13.0 → the
Ledger Service depends on it → the Ledger Service is part of the Payments
Platform.
Sources: vulnerabilities/cve-2021-44228-log4shell.md, libraries/log4j.md,
services/ledger-service.md

**B18. Which teams own a service that consumes an API owned by the Payments Team?**
Route: GRAPH
Gold: The Data Team (Fraud Service and Reporting Service consume the Ledger API;
Reporting also consumes the Billing API) and the Payments Team itself (Billing
consumes the Ledger API). The Ledger API and Billing API are owned by the
Payments Team.
Sources: services/fraud-service.md, services/reporting-service.md,
services/billing-service.md, services/ledger-service.md, teams/data-team.md,
teams/payments-team.md

---

## Category 4 — Aggregation / counting (Graph only)

**B24. How many services use PostgreSQL?**
Route: GRAPH
Gold: 5.
Sources: databases/postgresql.md

---

## Category 5 — Out of scope / should refuse

**B28. Is PostgreSQL better than MySQL for Meridian?**
Route: REFUSE
Gold: Opinion / not answerable from the corpus. The corpus states Meridian chose
PostgreSQL for strong consistency and its NUMERIC type, but makes no comparative
judgement against MySQL.
