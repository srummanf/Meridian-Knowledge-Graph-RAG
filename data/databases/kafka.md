# Kafka

**Type:** Database
**Aliases:** Apache Kafka, the event bus, event stream

## Overview

Kafka is Meridian's event streaming platform. The Ledger Service publishes a
transaction event to Kafka for every posted journal entry, and downstream
services consume that stream. Meridian runs Kafka 3.4.

## Deployment

Kafka is deployed on AWS EKS as a self-managed cluster using the Strimzi
operator.

## Usage at Meridian

The Ledger Service uses Kafka to publish transaction events.
The Notification Service uses Kafka to consume transaction events.
The Fraud Service uses Kafka to consume transaction events.

## Alternatives

Kafka is an alternative to RabbitMQ and to AWS Kinesis; Meridian chose Kafka for
durable, replayable event logs.
