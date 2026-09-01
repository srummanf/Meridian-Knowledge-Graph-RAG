# Billing Service

**Type:** Service
**Aliases:** billing-svc, the billing system
**Owner:** Payments Team
**Version:** 4.2

## Overview

The Billing Service produces invoices, runs subscription cycles, applies taxes,
and records what each merchant owes or is owed. It is part of the Payments
Platform.

## Composition

The Billing Service is part of the Payments Platform.

## Dependencies

The Billing Service depends on Django.
The Billing Service depends on Celery to run invoice generation and dunning as
background jobs.
The Billing Service depends on Python 3.11.

## Data & Storage

The Billing Service uses PostgreSQL to store invoices, line items, and payment
schedules.
The Billing Service uses Redis as its Celery broker and result backend.
The Billing Service handles PCI cardholder data, PII, and financial records.

## APIs

The Billing Service exposes the Billing API.
The Billing API communicates via REST.
The Billing Service consumes the Ledger API to post charges and the User API to
resolve merchant details.

## Security

The Billing Service is secured by RBAC; only finance-role principals can issue
credits or refunds.

## Deployment

The Billing Service is deployed on AWS EKS.

## Ownership

The Billing Service is owned by the Payments Team.
