# OAuth2

**Type:** SecurityMechanism
**Aliases:** OAuth, OAuth 2.0, OAuth2.0

## Overview

OAuth2 is the delegated-authorization framework Meridian uses to let merchants
and third-party apps act on a user's behalf without sharing passwords. The Auth
Service is the OAuth2 provider.

## Usage at Meridian

The Auth Service is secured by OAuth2 and implements the authorization-code flow.
The Public REST API is secured by OAuth2.
The Merchant Dashboard is authenticated with OAuth2.

## Notes

OAuth2 handles authorization only. Meridian pairs it with JWT for the access
token format and with RBAC for fine-grained permission checks.
