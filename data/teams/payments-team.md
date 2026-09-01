# Payments Team

**Type:** Team
**Aliases:** Payments Eng, the payments group

## Overview

The Payments Team owns the money-movement path: invoicing, the accounting ledger,
and the product that ties them together. It carries Meridian's PCI-DSS
responsibility.

## Ownership

The Billing Service is owned by the Payments Team.
The Ledger Service is owned by the Payments Team.
The Payments Platform is owned by the Payments Team.

## Responsibilities

The Payments Team is accountable for PCI compliance across every service that
handles PCI cardholder data. It reviews all changes to the Ledger Service
because the ledger is the system of record for customer funds.

## Dependencies on other teams

The Payments Team's services depend on the Auth Service and the User Service,
both owned by the Platform Team, and consume the Reporting API for reconciliation
checks.
