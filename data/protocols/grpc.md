# gRPC

**Type:** Protocol
**Aliases:** grpc, gRPC protocol

## Overview

gRPC is the binary, HTTP/2-based RPC protocol Meridian uses for internal
service-to-service calls that are latency-sensitive or high-volume.

## Usage at Meridian

The Auth API communicates via gRPC.
The Ledger API communicates via gRPC.
The User API communicates via gRPC for internal callers.

## Notes

Every internal gRPC endpoint at Meridian is secured by mTLS. gRPC is never
exposed directly to merchants; external access always goes through the Public
REST API on the API Gateway.
