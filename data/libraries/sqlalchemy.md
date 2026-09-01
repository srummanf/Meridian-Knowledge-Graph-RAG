# SQLAlchemy

**Type:** Library
**Aliases:** the ORM

## Overview

SQLAlchemy is the SQL toolkit and ORM used by Meridian's FastAPI services to talk
to PostgreSQL. Django services use Django's own ORM instead.

## Dependencies

SQLAlchemy depends on Python; it requires Python 3.7 or newer.

## Usage at Meridian

The User Service depends on SQLAlchemy.
The Reporting Service depends on SQLAlchemy.

## Version

Meridian uses SQLAlchemy 2.0, which is required for its async engine support.
