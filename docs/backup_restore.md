# OpenLIMS Backup and Restore Guide

## Purpose

This document explains how to back up and restore an OpenLIMS deployment using PostgreSQL, Docker Compose, and uploaded media files.

## What needs to be backed up

- PostgreSQL database
- Uploaded media files
- Environment configuration
- Docker Compose deployment files
- Application release version / Git tag

## PostgreSQL backup

```bash
cd ~/OpenLIMS

mkdir -p backups

docker compose -p openlims -f deploy/docker-compose.prod.yml exec db pg_dump \
  -U openlims \
  -d openlims \
  > backups/openlims_$(date +%Y%m%d_%H%M%S).sql

Fresh demo deployment:
- up -d --build
- migrate
- seed_demo

Restore existing data:
- choose a real backup file from backups/
- restore with psql
