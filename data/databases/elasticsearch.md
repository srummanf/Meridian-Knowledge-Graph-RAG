# Elasticsearch

**Type:** Database
**Aliases:** ES, OpenSearch, the search cluster

## Overview

Elasticsearch is Meridian's search and analytics engine. It is used for free-text
search and as a feature store for fraud scoring. Meridian runs Elasticsearch 8.3.

## Deployment

Elasticsearch is deployed on AWS EKS as a self-managed three-node cluster.

## Usage at Meridian

The Fraud Service uses Elasticsearch as a feature store.
The Reporting Service uses Elasticsearch for free-text search over transactions
and disputes.

## Alternatives

Elasticsearch is an alternative to OpenSearch and to PostgreSQL full-text search;
Meridian chose it for aggregations over large document sets.
