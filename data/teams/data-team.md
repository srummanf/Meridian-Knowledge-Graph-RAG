# Data Team

**Type:** Team
**Aliases:** Data Eng, the data group

## Overview

The Data Team owns analytics and risk: the product that reports on merchant
activity and the service that scores transactions for fraud in real time.

## Ownership

The Fraud Service is owned by the Data Team.
The Reporting Service is owned by the Data Team.
The Analytics Suite is owned by the Data Team.

## Responsibilities

The Data Team owns the fraud-model training pipeline, the analytics data
warehouse schema, and the freshness of the Reporting Service's read replica.

## Dependencies on other teams

The Data Team's services consume the Ledger API and the User API, read from the
Kafka event bus owned by the Payments Team, and depend on the Auth Service for
access control.
