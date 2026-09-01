# Analytics Suite

**Type:** Product
**Aliases:** Analytics, the analytics product
**Owner:** Data Team

## Overview

The Analytics Suite is a paid add-on product that gives merchants dashboards and
exports covering revenue trends, cohort retention, dispute rates, and settlement
timing.

## Composition

The Reporting Service is part of the Analytics Suite. The Reporting Service does
all of the query, aggregation, and export work that the Analytics Suite presents.

## Dependencies

The Analytics Suite consumes the Reporting API to fetch aggregated figures and to
trigger export jobs.

## Data

The Analytics Suite presents merchant business data and financial records. It
does not process PII directly; aggregation happens inside the Reporting Service.

## Ownership

The Analytics Suite is owned by the Data Team.
