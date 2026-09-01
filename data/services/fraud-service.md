# Fraud Service

**Type:** Service
**Aliases:** Fraud Detection Service, fraud-detection, the fraud scorer
**Owner:** Data Team
**Version:** 2.1

## Overview

The Fraud Service scores every transaction for fraud risk in real time and can
hold or decline a payment before it settles. It is part of the Payments
Platform.

## Composition

The Fraud Service is part of the Payments Platform.

## Dependencies

The Fraud Service depends on FastAPI.
The Fraud Service depends on Python 3.11.

## Data & Storage

The Fraud Service uses Kafka to consume the transaction events published by the
Ledger Service.
The Fraud Service uses Elasticsearch as a feature store for historical lookups
during scoring.
The Fraud Service uses Redis to cache recent scores and velocity counters.
The Fraud Service handles PII and financial records.

## APIs

The Fraud Service consumes the Ledger API to fetch entry detail and the User API
to fetch merchant risk attributes.

## Deployment

The Fraud Service is deployed on AWS EKS.

## Ownership

The Fraud Service is owned by the Data Team.
