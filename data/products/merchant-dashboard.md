# Merchant Dashboard

**Type:** Product
**Aliases:** the Dashboard, merchant portal
**Owner:** Growth Team

## Overview

The Merchant Dashboard is the web application merchants use to view payments,
manage their account, configure payouts, and read analytics. It is a single-page
application built with React.

## Dependencies

The Merchant Dashboard depends on React for its front-end.
The Merchant Dashboard consumes the Public REST API for all of its data; it does
not talk to internal services directly.

## Security

Access to the Merchant Dashboard is authenticated with OAuth2 and authorized with
RBAC, so that staff at a merchant only see the accounts and actions their role
permits.

## Data

The Merchant Dashboard displays merchant business data and financial records
retrieved through the Public REST API. It stores no data of its own beyond
browser session state.

## Ownership

The Merchant Dashboard is owned by the Growth Team.
