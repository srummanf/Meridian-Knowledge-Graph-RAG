# Payments Platform

**Type:** Product
**Aliases:** Payments, the payments product, MPP
**Owner:** Payments Team

## Overview

The Payments Platform is Meridian's flagship product. It lets merchants accept
card payments, run subscriptions, and reconcile settlements. It is a customer-
facing product assembled from several internal services rather than a single
deployable system.

## Composition

The Billing Service is part of the Payments Platform.
The Ledger Service is part of the Payments Platform.
The Fraud Service is part of the Payments Platform.

These three services together provide invoicing, double-entry accounting, and
real-time fraud scoring for every transaction that flows through the platform.

## Data & Compliance

Because it processes card transactions, the Payments Platform is in PCI-DSS
scope. Its component services handle PCI cardholder data and financial records.

## Ownership

The Payments Platform is owned by the Payments Team, which is accountable for its
availability, its PCI compliance posture, and its roadmap.
