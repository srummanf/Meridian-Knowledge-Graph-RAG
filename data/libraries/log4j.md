# Log4j

**Type:** Library
**Aliases:** log4j2, Apache Log4j

## Overview

Log4j is the Java logging library. At Meridian only the Ledger Service is written
in Java, so Log4j is used there and nowhere else.

## Dependencies

Log4j depends on Java.

## Usage at Meridian

The Ledger Service depends on Log4j version 2.13.0.

## Security

Log4j version 2.13.0 is affected by CVE-2021-44228, known as Log4Shell. The
Payments Team tracks the upgrade to a fixed 2.17.x release as a priority item.
