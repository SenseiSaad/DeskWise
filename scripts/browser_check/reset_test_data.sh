#!/usr/bin/env bash
# Delete the companies/users the browser checks create, so every run starts clean.
set -euo pipefail
cd "$(dirname "$0")/../.."
docker compose exec -T api python manage.py shell -c "
from core.models import Company, User
for slug in ('browser-test-co', 'partner-co'):
    c = Company.objects.filter(slug=slug).first()
    if c:
        User.objects.filter(company=c).delete(); c.delete()
print('remaining companies:', list(Company.objects.values_list('slug', flat=True)))
" 2>&1 | tail -1
