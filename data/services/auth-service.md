# Auth Service

**Type:** Service
**Aliases:** authn-svc, Authentication Service, the auth svc
**Owner:** Platform Team
**Version:** 5.4

## Overview

The Auth Service is Meridian's identity provider. It registers users, verifies
credentials, and issues tokens that every other service trusts. It implements the
OAuth2 authorization-code flow and mints JWT access tokens.

## Dependencies

The Auth Service depends on Django.
The Auth Service depends on Python 3.11.

## Data & Storage

The Auth Service uses PostgreSQL as its credential store.
The Auth Service uses Redis to cache active sessions and short-lived one-time
codes.
The Auth Service handles authentication credentials and PII.

## APIs

The Auth Service exposes the Auth API.
The Auth API communicates via gRPC as its primary protocol.

## Security

The Auth Service is secured by OAuth2; it is itself the OAuth2 provider for
Meridian.
The Auth API is secured by mTLS, so only services holding a valid client
certificate can call it.

## Deployment

The Auth Service is deployed on AWS EKS.

## Ownership

The Auth Service is owned by the Platform Team.
