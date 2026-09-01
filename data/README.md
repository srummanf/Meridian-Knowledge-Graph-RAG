# Meridian Corpus

The corpus for the Knowledge Graph RAG project. It is the internal architecture
wiki of **Meridian**, a fictional mid-size fintech company (payments processing +
merchant analytics).

Every document describes exactly one entity and states its relationships to other
entities in short, declarative sentences, so extraction evidence quotes are
clean and the graph is dense enough for real multi-hop questions.

## Structure

```
data/
├── ONTOLOGY.md        ← source of truth: types, relationships, aliases, IDs
├── SCHEMA.md          ← extraction output JSON shape + validation rules
├── README.md          ← this file
├── benchmark/
│   └── questions.md    ← 30 stratified benchmark questions with gold answers
├── products/     (3)   payments-platform, merchant-dashboard, analytics-suite
├── services/     (8)   api-gateway, auth-service, user-service, billing-service,
│                       ledger-service, notification-service, fraud-service,
│                       reporting-service
├── libraries/    (7)   django, fastapi, sqlalchemy, celery, log4j, python, java
├── databases/    (4)   postgresql, redis, elasticsearch, kafka
├── cloud/        (3)   aws-rds, aws-s3, aws-eks
├── protocols/    (2)   rest, grpc
├── security/     (4)   oauth2, jwt, mtls, rbac
├── teams/        (4)   platform-team, payments-team, growth-team, data-team
└── vulnerabilities/(2) cve-2021-44228-log4shell, cve-2024-0985-postgresql
```

**37 documents.** `python.md` and `java.md` are `Language` entities;
`log4j.md` is a `Library`.

## What the graph looks like after ingestion

Approximate (see `ONTOLOGY.md` §6 for the Phase 1 gates):

| | |
|---|---|
| Chunks (whole doc; split only if >350 tokens) | 40–55 |
| Distinct entities after resolution | 45–65 |
| Relationships | 140–200 |
| Entity types present | 11 |
| Relationship types present | 12 |

## Entity types (11)

`Product` · `Service` · `API` · `Library` · `Language` · `Database` ·
`CloudService` · `Protocol` · `SecurityMechanism` · `Team` · `Vulnerability`

## Relationship types (12)

`PART_OF` · `DEPENDS_ON` · `USES` · `EXPOSES` · `CONSUMES` · `COMMUNICATES_VIA` ·
`SECURED_BY` · `DEPLOYED_ON` · `OWNED_BY` · `HANDLES` · `AFFECTS` ·
`ALTERNATIVE_TO`

## Deliberate multi-hop chains

The corpus is wired so these questions have real answers (full list in
`ONTOLOGY.md` §7):

- **CVE blast radius** — CVE → Library → Service → Product
  (*"if Log4Shell is exploited, which products are affected?"* → Payments Platform)
- **Cross-team dependency** — Team ← Service → API ← Service → Team
  (*"which teams depend on an API the Payments Team owns?"*)
- **Data-compliance exposure** — Service → "PII" and Service → Database → CloudService
- **Stack rollup** — Product ← Service → Library → Language
- **Shared-infrastructure aggregation** — `count` services per database

## Built-in entity-resolution cases

Aliases are seeded through the text so Phase 1.4 has real work to do:
`Postgres` / `PG` / `RDS Postgres` → **PostgreSQL**; `authn-svc` /
`Authentication Service` → **Auth Service**; `the event bus` → **Kafka**;
`OAuth` / `OAuth 2.0` → **OAuth2**; `the gateway` / `api-gw` → **API Gateway**.
Full table in `ONTOLOGY.md` §3.

## Document template

Each document uses a subset of these `##` sections. A whole document is one chunk
(`chunk_id = <path>`) unless it exceeds ~350 tokens, in which case it splits per
section (`chunk_id = <path>#<section-slug>`):

`Overview` · `Composition` · `Dependencies` · `Data & Storage` · `APIs` ·
`Security` · `Deployment` · `Ownership` · `Alternatives` · `Version` ·
`Notes` / `Status`
