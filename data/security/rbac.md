# RBAC

**Type:** SecurityMechanism
**Aliases:** role-based access control

## Overview

RBAC is role-based access control: permissions are attached to roles, and roles
are assigned to users. Meridian uses it for fine-grained checks after a caller is
authenticated.

## Usage at Meridian

The Billing Service is secured by RBAC; only finance-role principals can issue
credits or refunds.
The Merchant Dashboard is authorized with RBAC so staff at a merchant see only
what their role permits.

## Notes

Role assignments live in the User Service. Services fetch a caller's roles from
the User API and enforce RBAC locally.
