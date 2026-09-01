# Redis

**Type:** Database
**Aliases:** Redis cache, in-memory store

## Overview

Redis is Meridian's in-memory data store. It is used for caching, for session
storage, and as the Celery broker. Meridian runs Redis 7.0.

## Deployment

Redis is deployed on AWS EKS as a self-managed StatefulSet with one primary and
two replicas; it is not on a managed Redis service.

## Usage at Meridian

The Auth Service uses Redis to cache sessions.
The Billing Service uses Redis as its Celery broker.
The Notification Service uses Redis as its delivery queue.
The Fraud Service uses Redis to cache scores and velocity counters.

## Alternatives

Redis is an alternative to Memcached; Meridian chose Redis for its data
structures and persistence options.
