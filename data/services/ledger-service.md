# Ledger Service

**Type:** Service
**Aliases:** the ledger, ledger-svc, General Ledger service
**Owner:** Payments Team
**Version:** 6.0

## Overview

The Ledger Service is the system of record for customer funds. Every movement of
money is written as a double-entry journal entry. It is the most tightly
controlled service at Meridian and is part of the Payments Platform.

## Composition

The Ledger Service is part of the Payments Platform.

## Dependencies

The Ledger Service depends on Java 17.
The Ledger Service depends on Log4j version 2.13.0 for application logging.

## Data & Storage

The Ledger Service uses PostgreSQL to hold the journal and account balances.
The Ledger Service uses Kafka to publish a transaction event for every posted
entry.
The Ledger Service uses AWS S3 to archive immutable monthly statements.
The Ledger Service handles financial records and PCI cardholder data.

## APIs

The Ledger Service exposes the Ledger API.
The Ledger API communicates via gRPC.
The Billing Service, the Fraud Service, and the Reporting Service all consume the
Ledger API.

## Security

The Ledger API is secured by mTLS.

## Deployment

The Ledger Service is deployed on AWS EKS.

## Ownership

The Ledger Service is owned by the Payments Team.
