#!/usr/bin/env bash
# Full workspace browser verification against a running stack (docker compose up).
# Needs: /tmp/pwenv with playwright (see common.py) and Chrome at /usr/bin/google-chrome.
set -uo pipefail
cd "$(dirname "$0")/../.."
PY=${PY:-/tmp/pwenv/bin/python}
EV=docs/evidence/workspace-browser
rm -f "$EV"/*.png "$EV"/results.jsonl
scripts/browser_check/reset_test_data.sh
$PY scripts/browser_check/explore_admin.py | grep -E "SIGNUP|^===" 
$PY scripts/browser_check/admin_a.py
CODE=$(docker compose exec -T api python manage.py shell -c "from core.models import Company; print(Company.objects.get(slug='browser-test-co').access_code)" 2>/dev/null | tail -1 | tr -d '\r\n')
if [ -z "$CODE" ] || [ ${#CODE} -lt 5 ]; then
  CODE=$($PY - <<'PYEOF'
import re, sys
sys.path.insert(0, "scripts/browser_check")
from playwright.sync_api import sync_playwright
from common import *
with sync_playwright() as pw:
    s = Session(pw, "tmp"); login(s, "admin@browsertest.test", "Br0wser-Test-Pass!7", "admin")
    m = re.search(r"Company code\s+([A-Z0-9]{5,8})", s.page.locator("body").inner_text())
    print(m.group(1) if m else ""); s.close()
PYEOF
)
fi
echo "Browser Test Co code: $CODE"
$PY scripts/browser_check/partner_share.py "$CODE"
$PY scripts/browser_check/admin_b.py
$PY scripts/browser_check/employee.py
