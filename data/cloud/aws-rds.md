# AWS RDS

**Type:** CloudService
**Aliases:** RDS, Amazon RDS, managed Postgres

## Overview

AWS RDS is Amazon's managed relational database service. Meridian uses it to run
PostgreSQL without operating the database hosts itself.

## Usage at Meridian

PostgreSQL is deployed on AWS RDS.
Meridian runs one Multi-AZ primary instance and one read replica on AWS RDS.

## Responsibility

AWS manages patching, backups, and failover for the database engine. The Platform
Team owns the instance configuration, parameter groups, and the schedule for
applying engine version upgrades.
