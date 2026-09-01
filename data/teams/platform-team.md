# Platform Team

**Type:** Team
**Aliases:** Platform, the platform group

## Overview

The Platform Team builds and operates Meridian's shared infrastructure: the edge
that external traffic enters through, identity, and user profiles. Other teams
build on top of what the Platform Team owns.

## Ownership

The API Gateway is owned by the Platform Team.
The Auth Service is owned by the Platform Team.
The User Service is owned by the Platform Team.

## Responsibilities

The Platform Team owns the Public REST API contract, the OAuth2 provider
configuration, and the mTLS certificate authority used for internal service-to-
service calls.

## On-call

The Platform Team runs a 24/7 on-call rotation because an outage in the API
Gateway or Auth Service takes down every product at once.
