#!/usr/bin/env bash
set -euo pipefail

# Usage:
# DJANGO_ADMIN_USERNAME=admin DJANGO_ADMIN_EMAIL=admin@example.com DJANGO_ADMIN_PASSWORD=pass bash scripts/init_admin.sh

: "${DJANGO_ADMIN_USERNAME:?Set DJANGO_ADMIN_USERNAME}"
: "${DJANGO_ADMIN_EMAIL:?Set DJANGO_ADMIN_EMAIL}"
: "${DJANGO_ADMIN_PASSWORD:?Set DJANGO_ADMIN_PASSWORD}"

docker compose -f deploy/docker-compose.yml run --rm api python manage.py shell -c "
from django.contrib.auth import get_user_model;
User=get_user_model();
u, created = User.objects.get_or_create(username='${DJANGO_ADMIN_USERNAME}', defaults={'email':'${DJANGO_ADMIN_EMAIL}'});
if created:
    u.set_password('${DJANGO_ADMIN_PASSWORD}');
    u.is_staff=True; u.is_superuser=True;
    u.save();
    print('Created superuser:', u.username)
else:
    print('Superuser already exists:', u.username)
"
