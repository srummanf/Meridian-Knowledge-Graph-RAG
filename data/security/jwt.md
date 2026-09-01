# JWT

**Type:** SecurityMechanism
**Aliases:** JSON Web Token, bearer token

## Overview

JWT is the signed token format Meridian uses for access tokens. The Auth Service
mints JWTs; every other service verifies them.

## Usage at Meridian

The Public REST API is secured by JWT.
The API Gateway validates the JWT signature and expiry on every request.
The Auth Service issues JWT access tokens as part of the OAuth2 flow.

## Notes

Meridian JWTs are short-lived (15 minutes) and are refreshed against the Auth
Service. Tokens are signed with a rotating RS256 key published at a JWKS
endpoint.
