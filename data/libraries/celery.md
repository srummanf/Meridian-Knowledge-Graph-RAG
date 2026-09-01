# Celery

**Type:** Library
**Aliases:** —

## Overview

Celery is a distributed task queue for Python. Meridian services use it to run
work outside the request path: invoice generation, notification retries, and
scheduled jobs.

## Dependencies

Celery depends on Python.
Celery depends on Redis, which Meridian uses as the Celery broker and result
backend.

## Usage at Meridian

The Billing Service depends on Celery.
The Notification Service depends on Celery.

## Version

Meridian uses Celery 5.3.
