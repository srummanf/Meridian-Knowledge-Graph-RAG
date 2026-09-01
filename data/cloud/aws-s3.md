# AWS S3

**Type:** CloudService
**Aliases:** S3, object storage

## Overview

AWS S3 is Amazon's object storage service. Meridian uses it for large immutable
artifacts: statement archives, rendered attachments, and analytics exports.

## Usage at Meridian

The Ledger Service uses AWS S3 to archive monthly statements.
The Notification Service uses AWS S3 to store rendered PDF attachments.
The Reporting Service uses AWS S3 to hold generated CSV and Parquet exports.

## Security

All Meridian S3 buckets have default encryption enabled and block all public
access. Statement-archive buckets additionally use Object Lock so records cannot
be deleted before their retention period ends.
