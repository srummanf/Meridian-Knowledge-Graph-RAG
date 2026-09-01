# User Service

**Type:** Service
**Aliases:** user-svc, Profile Service
**Owner:** Platform Team
**Version:** 2.8

## Overview

The User Service owns merchant and staff profile data: names, contact details,
roles, business metadata, and account settings. Other services call it whenever
they need to resolve who a request belongs to.

## Dependencies

The User Service depends on FastAPI.
The User Service depends on SQLAlchemy as its ORM.
The User Service depends on Python 3.11.
The User Service depends on the Auth Service to validate tokens before returning
any profile data.

## Data & Storage

The User Service uses PostgreSQL to store profiles and role assignments.
The User Service handles PII and merchant business data.

## APIs

The User Service exposes the User API.
The User API communicates via REST and also via gRPC for internal callers.
The API Gateway, the Billing Service, the Notification Service, the Fraud
Service, and the Reporting Service all consume the User API.

## Security

The User API is secured by mTLS for internal traffic.

## Deployment

The User Service is deployed on AWS EKS.

## Ownership

The User Service is owned by the Platform Team.
