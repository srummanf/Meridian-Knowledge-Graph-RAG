# PostgreSQL

**Type:** Database
**Aliases:** Postgres, PG, psql, RDS Postgres

## Overview

PostgreSQL is Meridian's default relational database. It is used by every service
that needs transactional, relational storage. Meridian runs PostgreSQL version
14.2.

## Deployment

PostgreSQL is deployed on AWS RDS as a Multi-AZ managed instance. The Reporting
Service reads from a dedicated RDS read replica.

## Usage at Meridian

The Auth Service uses PostgreSQL.
The User Service uses PostgreSQL.
The Billing Service uses PostgreSQL.
The Ledger Service uses PostgreSQL.
The Reporting Service uses PostgreSQL.

## Alternatives

PostgreSQL is an alternative to other relational databases; Meridian chose it for
its strong consistency guarantees and its `NUMERIC` type for money.

## Security

PostgreSQL version 14.2 is affected by CVE-2024-0985. The Platform Team tracks
the upgrade to 14.11 or later.
