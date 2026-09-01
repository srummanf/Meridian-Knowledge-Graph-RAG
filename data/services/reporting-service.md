# Reporting Service

**Type:** Service
**Aliases:** reporting-svc, the reporting backend
**Owner:** Data Team
**Version:** 1.9

## Overview

The Reporting Service runs the queries, aggregations, and export jobs behind the
Analytics Suite. It is part of the Analytics Suite.

## Composition

The Reporting Service is part of the Analytics Suite.

## Dependencies

The Reporting Service depends on FastAPI.
The Reporting Service depends on SQLAlchemy as its ORM.
The Reporting Service depends on Python 3.11.

## Data & Storage

The Reporting Service uses PostgreSQL, reading from a dedicated read replica so
that heavy analytics queries do not affect transactional workloads.
The Reporting Service uses Elasticsearch to power free-text search over
transactions and disputes.
The Reporting Service uses AWS S3 to hold generated CSV and Parquet exports.
The Reporting Service handles merchant business data and financial records.

## APIs

The Reporting Service exposes the Reporting API.
The Reporting API communicates via REST.
The Reporting Service consumes the Ledger API and the Billing API to reconcile
aggregates against the source systems.

## Deployment

The Reporting Service is deployed on AWS EKS.

## Ownership

The Reporting Service is owned by the Data Team.
