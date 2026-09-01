# API Gateway

**Type:** Service
**Aliases:** the gateway, api-gw, edge gateway
**Owner:** Platform Team
**Version:** 3.1

## Overview

The API Gateway is the single entry point for all traffic from outside Meridian.
It terminates TLS, authenticates callers, applies rate limits, and routes each
request to the internal service that can answer it.

## Dependencies

The API Gateway depends on FastAPI.
The API Gateway depends on Python 3.11.

## APIs

The API Gateway exposes the Public REST API.
The Public REST API communicates via REST as its primary protocol.
The API Gateway consumes the Auth API to validate every incoming token.
The API Gateway consumes the User API and the Ledger API to serve merchant
requests.

## Security

The Public REST API is secured by OAuth2 for delegated authorization.
The Public REST API is secured by JWT; the gateway validates the bearer token's
signature and expiry on every request before routing it.

## Deployment

The API Gateway is deployed on AWS EKS, running as a horizontally scaled
deployment behind a network load balancer.

## Ownership

The API Gateway is owned by the Platform Team.
