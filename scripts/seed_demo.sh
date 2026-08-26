#!/usr/bin/env bash
set -euo pipefail

docker compose -f deploy/docker-compose.yml run --rm api python manage.py seed_demo
