# Notification Service

**Type:** Service
**Aliases:** Notifications, notif-svc, the notification system
**Owner:** Growth Team
**Version:** 3.5

## Overview

The Notification Service delivers transactional email, SMS, and outbound webhooks
to merchants: payment receipts, payout alerts, dispute notices, and dunning
reminders.

## Dependencies

The Notification Service depends on FastAPI.
The Notification Service depends on Celery to retry deliveries with backoff.
The Notification Service depends on Python 3.11.

## Data & Storage

The Notification Service uses Redis as its Celery broker and delivery queue.
The Notification Service uses AWS S3 to store rendered attachments such as PDF
receipts.
The Notification Service uses Kafka to consume transaction events published by
the Ledger Service.
The Notification Service handles PII.

## APIs

The Notification Service consumes the User API to look up a merchant's contact
preferences and locale.

## Deployment

The Notification Service is deployed on AWS EKS.

## Ownership

The Notification Service is owned by the Growth Team.
