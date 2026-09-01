# Meridian Knowledge Graph — Ontology

**This file is the single source of truth for entity types, relationship types,
canonicalisation, and aliases.** The extraction prompt, the Pydantic models, and
the Cypher templates all derive from this document. If `SCHEMA.md` and this file
ever disagree, this file wins.

Corpus context: **Meridian** is a fictional mid-size fintech company (payments
processing + merchant analytics). The corpus is Meridian's internal architecture
wiki. Every document describes one entity and states its relationships to other
entities in plain, declarative sentences so that extraction evidence quotes are
clean.

---

## 1. Entity Types (11)

Each entity has: `id` (deterministic — see §4), `type`, `canonical_name`,
`aliases[]`, `properties{}`, `confidence`, `source_chunk_id`.

| # | Type | Definition | Examples |
|---|------|------------|----------|
| 1 | `Product` | A customer-facing offering Meridian sells or exposes to merchants. | Payments Platform, Merchant Dashboard, Analytics Suite |
| 2 | `Service` | An internal, independently deployable system Meridian runs itself (a microservice). | Auth Service, Billing Service, Ledger Service |
| 3 | `API` | A named API surface that a Service exposes for other services or external callers. | Public REST API, Auth API, Ledger API |
| 4 | `Library` | A third-party package or framework pulled in as a dependency (pip / npm / maven). | Django, FastAPI, SQLAlchemy, Celery, Log4j |
| 5 | `Language` | A programming language or runtime. | Python, Java |
| 6 | `Database` | A data store (relational, cache, search, streaming). Always `Database`, never `Product` or `Library`. | PostgreSQL, Redis, Elasticsearch, Kafka |
| 7 | `CloudService` | A provider-managed cloud offering. | AWS RDS, AWS S3, AWS EKS |
| 8 | `Protocol` | A communication standard or wire format. | REST, gRPC |
| 9 | `SecurityMechanism` | An authentication, authorization, or transport-security mechanism. | OAuth2, JWT, mTLS, RBAC |
| 10 | `Team` | An engineering team that owns services/products. | Platform Team, Payments Team |
| 11 | `Vulnerability` | A published CVE that affects a specific library or database version range. | CVE-2021-44228 (Log4Shell) |

### Type precedence (resolve ambiguity in this order)

When an entity could plausibly be more than one type, assign the **first**
matching rule:

1. It is a CVE identifier → `Vulnerability`
2. It is a programming language or runtime → `Language`
3. It is a data store (persists or caches data, or is a message/stream broker) → `Database`
4. It is provider-managed cloud infrastructure → `CloudService`
5. It is a wire protocol or format → `Protocol`
6. It is an auth / authz / transport-security mechanism → `SecurityMechanism`
7. It is an engineering team → `Team`
8. It is a named API surface exposed by a service → `API`
9. It is installed as a package / framework dependency → `Library`
10. It is a system Meridian deploys and operates itself → `Service`
11. It is a customer-facing offering → `Product`

So: PostgreSQL is a `Database` (not `Product`). Django is a `Library` (not
`Product`). The Payments Platform is a `Product` (not `Service`), even though it
is made of services.

---

## 2. Relationship Types (12, all directional unless noted)

Relationships are **never inferred** — only extracted when a sentence in the
chunk states them. Every relationship carries `source_chunk_id`, `evidence`
(exact quote), `confidence`, and any listed properties.

| Type | Direction | Meaning | Typical endpoints | Properties |
|------|-----------|---------|-------------------|------------|
| `PART_OF` | A → B | A is a component of product B | Service → Product | — |
| `DEPENDS_ON` | A → B | A requires B to function | Service → Library, Service → Service, Library → Library, Library → Language | `optional` (bool), `version_constraint` |
| `USES` | A → B | A actively uses B but is not broken without it | Service → Database, Service → CloudService | `purpose` (string) |
| `EXPOSES` | A → B | A publishes API surface B | Service → API | — |
| `CONSUMES` | A → B | A calls API surface B (owned by another service) | Service → API | — |
| `COMMUNICATES_VIA` | A → B | API A speaks protocol B | API → Protocol | `primary` (bool) |
| `SECURED_BY` | A → B | A is protected by security mechanism B | API → SecurityMechanism, Service → SecurityMechanism | — |
| `DEPLOYED_ON` | A → B | A runs on infrastructure B | Service → CloudService, Database → CloudService | — |
| `OWNED_BY` | A → B | Team B owns/operates A | Service → Team, Product → Team, API → Team | — |
| `HANDLES` | A → B | A processes data category / concern B | Service → concern (`"PII"`, `"PCI cardholder data"`, `"financial records"`) | — |
| `AFFECTS` | A → B | Vulnerability A affects B | Vulnerability → Library, Vulnerability → Database | `affected_versions` (string) |
| `ALTERNATIVE_TO` | A ↔ B (bidirectional) | A and B solve the same problem | Database ↔ Database, Library ↔ Library | — |

**Notes**
- `HANDLES` targets are a small controlled vocabulary of data-concern strings,
  not entities. Allowed values: `PII`, `PCI cardholder data`, `financial records`,
  `authentication credentials`, `merchant business data`.
- Bidirectional (`ALTERNATIVE_TO`): store **one** edge; the graph retriever
  queries it undirected. Do not write both directions.
- `REQUIRES` from the old schema is **removed** — it was a synonym for
  `DEPENDS_ON`. Use `DEPENDS_ON` with `optional: false`.
- `USED_BY`, `PROVIDED_BY`, `BACKS`, `PROVIDES` from old docs are **removed**.
  Direction is always expressed with the canonical type above; the retriever
  reverses it in Cypher when a question asks "what uses X".

---

## 3. Canonicalisation & Alias List

Extraction must map every mention to the canonical name below. The alias list is
also the seed for the entity-resolution step (Phase 1.4).

| Canonical name | Type | Aliases seen in corpus |
|----------------|------|------------------------|
| PostgreSQL | Database | Postgres, PG, psql, RDS Postgres |
| Redis | Database | Redis cache, in-memory store |
| Elasticsearch | Database | ES, OpenSearch, the search cluster |
| Kafka | Database | Apache Kafka, the event bus, event stream |
| Auth Service | Service | authn-svc, Authentication Service, the auth svc |
| API Gateway | Service | the gateway, api-gw, edge gateway |
| User Service | Service | user-svc, Profile Service |
| Billing Service | Service | billing-svc, the billing system |
| Ledger Service | Service | the ledger, ledger-svc, General Ledger service |
| Notification Service | Service | Notifications, notif-svc, the notification system |
| Fraud Service | Service | Fraud Detection Service, fraud-detection, the fraud scorer |
| Payments Platform | Product | Payments, the payments product, MPP |
| Merchant Dashboard | Product | the Dashboard, merchant portal |
| Analytics Suite | Product | Analytics, the analytics product |
| OAuth2 | SecurityMechanism | OAuth, OAuth 2.0, OAuth2.0 |
| JWT | SecurityMechanism | JSON Web Token, bearer token |
| mTLS | SecurityMechanism | mutual TLS, client-cert auth |
| RBAC | SecurityMechanism | role-based access control |
| AWS RDS | CloudService | RDS, Amazon RDS, managed Postgres |
| AWS S3 | CloudService | S3, object storage |
| AWS EKS | CloudService | EKS, the Kubernetes cluster, k8s |
| Django | Library | — |
| FastAPI | Library | — |
| SQLAlchemy | Library | the ORM |
| Celery | Library | — |
| Log4j | Library | log4j2, Apache Log4j |
| Python | Language | — |
| Java | Language | JVM |

Canonicalisation rules:
1. Strip surrounding articles ("the gateway" → `API Gateway`).
2. Expand known acronyms per the table.
3. Case-fold for comparison but store the canonical casing above.
4. A version suffix ("PostgreSQL 14.2") is **not** part of the name — it goes in
   `properties.version`.

---

## 4. Entity ID Scheme

`id = "<type_lowercase>:<slug(canonical_name)>"` where `slug` lowercases,
replaces spaces/dots with `-`, and strips other punctuation.

Examples: `database:postgresql`, `service:auth-service`,
`securitymechanism:oauth2`, `vulnerability:cve-2021-44228`.

This is deterministic, so `MERGE (e:Entity {id: $id})` is idempotent across
re-runs. No UUIDs.

---

## 5. Confidence

- `0.95–1.0` — relationship stated explicitly in one sentence.
- `0.80–0.94` — stated across two sentences in the same chunk, or lightly paraphrased.
- `< 0.80` — **do not extract.** Drop it.

---

## 6. Realistic Corpus Targets (for Phase 1 gates)

Measured against this corpus (37 documents; chunk = whole doc, split by section
only if a doc exceeds ~350 tokens):

| Metric | Target |
|--------|--------|
| Chunks | 40–55 |
| Distinct entities (after resolution) | 45–65 |
| Relationships | 140–200 |
| Entity-resolution: alias-table cases merged | 100% |
| Entity extraction F1 | ≥ 0.85 |
| Relationship extraction F1 | ≥ 0.75 |

Gold set = the ~25 relationships the benchmark depends on, hand-labelled — not a
full annotation. Entities recur heavily (PostgreSQL, Python, AWS EKS, the teams,
the protocols appear in many docs), so the distinct-entity count is well below
the doc count.

---

## 7. Deliberate Multi-Hop Chains

These are wired into the corpus on purpose so the Phase 5 benchmark has real
answers. The "widening gap vs. vector RAG" story depends on them.

```
A. CVE blast radius (4 hops)
   Vulnerability -AFFECTS-> Library <-DEPENDS_ON- Service -PART_OF-> Product

B. Cross-team dependency (4 hops)
   Team <-OWNED_BY- Service -CONSUMES-> API <-EXPOSES- Service -OWNED_BY-> Team

C. Data-compliance exposure (3 hops)
   Service -HANDLES-> "PII"   AND   Service -USES-> Database -DEPLOYED_ON-> CloudService

D. Stack rollup (3 hops)
   Product <-PART_OF- Service -DEPENDS_ON-> Library -DEPENDS_ON-> Language

E. Shared-infrastructure aggregation (1–2 hops, COUNT / GROUP BY)
   MATCH (s:Service)-[:USES]->(d:Database {canonical_name:'PostgreSQL'}) RETURN count(s)
```
