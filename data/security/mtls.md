# mTLS

**Type:** SecurityMechanism
**Aliases:** mutual TLS, client-cert auth

## Overview

mTLS is mutual TLS: both sides of a connection present a certificate. Meridian
uses it so that only known services can call internal gRPC APIs.

## Usage at Meridian

The Auth API is secured by mTLS.
The Ledger API is secured by mTLS.
The User API is secured by mTLS for internal traffic.

## Notes

The Platform Team runs the internal certificate authority that issues service
certificates. Certificates are rotated every 90 days automatically.
