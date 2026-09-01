# Benchmark Questions — Meridian Knowledge Graph

30 questions for the Phase 5 comparison of Graph RAG vs. vector-only RAG.
Stratified by hop count. Each has a gold answer grounded in the corpus and the
route it *should* take.

Phase 5 converts this file to `tests/fixtures/benchmark_questions.json`.
Expected shape: parity on 1-hop, Graph pulls ahead on 2-hop, wide gap on 3-hop
and aggregation.

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

**B11. What does the Billing Service depend on?**
Route: GRAPH
Gold: Django, Celery, Python (libraries/language); it also uses PostgreSQL and
Redis and consumes the Ledger API and User API.
Sources: services/billing-service.md

**B12. Which services does the Growth Team own?**
Route: GRAPH
Gold: Merchant Dashboard (product) and Notification Service.
Sources: teams/growth-team.md#ownership

**B13. Which APIs are secured by mTLS?**
Route: GRAPH
Gold: Auth API, Ledger API, User API.
Sources: security/mtls.md#usage-at-meridian

**B14. Which services consume the Ledger API?**
Route: GRAPH
Gold: Billing Service, Fraud Service, Reporting Service.
Sources: services/ledger-service.md#apis

**B15. Which services handle PII?**
Route: GRAPH
Gold: Auth Service, User Service, Billing Service, Notification Service, Fraud
Service.
Sources: HANDLES edges across the five service docs

**B16. What is the Payments Platform made of?**
Route: GRAPH
Gold: Billing Service, Ledger Service, Fraud Service.
Sources: products/payments-platform.md#composition

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
Sources: services/{fraud,reporting,billing,ledger}-service.md, teams/*.md

**B19. Which PostgreSQL-backed services are also exposed to the Log4Shell blast radius?**
Route: GRAPH
Gold: Only the Ledger Service — it uses PostgreSQL and depends on the affected
Log4j. (Auth, User, Billing, Reporting use PostgreSQL but are Python services
with no Log4j.)
Sources: databases/postgresql.md, libraries/log4j.md, services/ledger-service.md

**B20. Which services both handle PCI cardholder data and are deployed on AWS EKS?**
Route: GRAPH
Gold: Billing Service and Ledger Service (both HANDLES "PCI cardholder data",
both DEPLOYED_ON AWS EKS).
Sources: services/billing-service.md, services/ledger-service.md

**B21. Through which chain does the Analytics Suite get ledger data?**
Route: GRAPH
Gold: Analytics Suite → contains the Reporting Service → Reporting Service
consumes the Ledger API → Ledger API is exposed by the Ledger Service.
Sources: products/analytics-suite.md, services/reporting-service.md,
services/ledger-service.md

**B22. Which databases used by Payments Platform services are self-managed on EKS rather than on a managed AWS service?**
Route: GRAPH
Gold: Redis, Kafka, and Elasticsearch (used by Billing/Ledger/Fraud) run
self-managed on AWS EKS. PostgreSQL, also used, is on managed AWS RDS.
Sources: databases/*.md, services/{billing,ledger,fraud}-service.md

**B23. Which teams would need to be involved to upgrade PostgreSQL off the version affected by CVE-2024-0985?**
Route: GRAPH
Gold: The Platform Team owns the RDS instance and the upgrade; the Payments Team
(Billing, Ledger) and Data Team (Reporting) plus Platform (Auth, User) own
services running against it and would need to validate.
Sources: vulnerabilities/cve-2024-0985-postgresql.md, databases/postgresql.md,
teams/*.md

---

## Category 4 — Aggregation / counting (Graph only)

**B24. How many services use PostgreSQL?**
Route: GRAPH
Gold: 5.
Sources: databases/postgresql.md

**B25. How many services are deployed on AWS EKS?**
Route: GRAPH
Gold: 8 services (API Gateway, Auth, User, Billing, Ledger, Notification, Fraud,
Reporting). Redis, Elasticsearch, and Kafka also run there but are databases.
Sources: cloud/aws-eks.md + service docs

**B26. Which database has the most services using it?**
Route: GRAPH
Gold: PostgreSQL, with 5 services. Redis has 4.
Sources: databases/postgresql.md, databases/redis.md

**B27. How many distinct services does the Data Team's Reporting Service depend on or consume APIs from?**
Route: GRAPH
Gold: 2 — it consumes the Ledger API (Ledger Service) and the Billing API
(Billing Service).
Sources: services/reporting-service.md

---

## Category 5 — Out of scope / should refuse

**B28. Is PostgreSQL better than MySQL for Meridian?**
Route: REFUSE
Gold: Opinion / not answerable from the corpus. The corpus states Meridian chose
PostgreSQL for strong consistency and its NUMERIC type, but makes no comparative
judgement against MySQL.

**B29. Should the Payments Team rewrite the Ledger Service in Go?**
Route: REFUSE
Gold: Recommendation / out of scope. The corpus documents the current stack
(Java 17) but contains no basis for a rewrite recommendation.

**B30. What will Meridian's transaction volume be next year?**
Route: REFUSE
Gold: Not in the corpus. The knowledge graph describes architecture and
ownership, not business forecasts.
