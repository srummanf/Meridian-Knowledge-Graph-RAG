# AWS EKS

**Type:** CloudService
**Aliases:** EKS, the Kubernetes cluster, k8s

## Overview

AWS EKS is Amazon's managed Kubernetes service. Every Meridian service runs as a
workload on a single shared EKS cluster, and several stateful systems run there
too.

## Usage at Meridian

The API Gateway is deployed on AWS EKS.
The Auth Service, User Service, Billing Service, Ledger Service, Notification
Service, Fraud Service, and Reporting Service are all deployed on AWS EKS.
Redis, Elasticsearch, and Kafka are also deployed on AWS EKS as self-managed
workloads.

## Responsibility

AWS manages the Kubernetes control plane. The Platform Team owns the node groups,
cluster add-ons, and namespace-level resource quotas.
