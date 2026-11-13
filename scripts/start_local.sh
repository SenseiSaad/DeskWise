#!/usr/bin/env bash
# ==============================================================================
# Deskwise — Zero-Step Local Launcher
#
# Usage:
#   ./scripts/start_local.sh            # Docker Compose mode (recommended)
#   ./scripts/start_local.sh --native   # Bare-metal mode (Python + Node on host)
#   ./scripts/start_local.sh --stop     # Stop running containers / dev servers
#
# What this script does automatically on a brand-new clone:
#   1. Creates .env (and backend/.env for --native) from .env.example if missing
#   2. Generates fresh cryptographic SECRET_KEY and LLM_KEY_ENCRYPTION_KEY
#   3. Builds & starts API (:8000) + Web (:3000)
#   4. Runs database migrations + seeds default subscription plans
#   5. Seeds a ready-to-test Demo Company + sample HR policy & template docs
#   6. Prints http://localhost:3000 + generated demo login credentials
# ==============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

gen_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 48 | tr '+/' '-_' | tr -d '=\n'
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
  else
    head -c 48 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n'
  fi
}

gen_demo_password() {
  local suffix
  if command -v openssl >/dev/null 2>&1; then
    suffix="$(openssl rand -hex 6)"
  else
    suffix="$(head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  fi
  echo "OvDemo!${suffix}9A"
}

ensure_env_file() {
  local target="$1"
  local template="$2"
  if [[ ! -f "$target" ]]; then
    cp "$template" "$target"
    echo "[deskwise] Created $target from $template"
  fi

  if grep -qE '^SECRET_KEY=\s*$' "$target"; then
    local sk
    sk="$(gen_secret)"
    sed -i.bak "s|^SECRET_KEY=.*|SECRET_KEY=${sk}|" "$target" && rm -f "${target}.bak"
    echo "[deskwise] Generated fresh SECRET_KEY in $target"
  fi

  if grep -qE '^LLM_KEY_ENCRYPTION_KEY=\s*$' "$target"; then
    local lk
    lk="$(gen_secret)"
    sed -i.bak "s|^LLM_KEY_ENCRYPTION_KEY=.*|LLM_KEY_ENCRYPTION_KEY=${lk}|" "$target" && rm -f "${target}.bak"
    echo "[deskwise] Generated fresh LLM_KEY_ENCRYPTION_KEY in $target"
  fi
}

wait_for_url() {
  local url="$1"
  local label="$2"
  local max_tries="${3:-60}"
  local i=1
  while (( i <= max_tries )); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "[deskwise] $label is healthy ($url)"
      return 0
    fi
    sleep 2
    (( i++ ))
  done
  echo "[deskwise] ERROR: Timed out waiting for $label at $url" >&2
  return 1
}

env_value() {  # env_value FILE KEY DEFAULT -> value from FILE (uncommented) or DEFAULT
  local v
  v="$(grep -E "^$2=" "$1" 2>/dev/null | tail -1 | cut -d= -f2- || true)"
  echo "${v:-$3}"
}

port_in_use() {
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1$"
  elif command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else
    return 1
  fi
}

check_ports() {  # check_ports API_PORT WEB_PORT
  local busy=0 p
  for p in "$1" "$2"; do
    if port_in_use "$p"; then
      echo "[deskwise] ERROR: host port $p is already in use." >&2
      busy=1
    fi
  done
  if (( busy )); then
    echo "[deskwise] Stop whatever is using it (e.g. ./stop.sh)," >&2
    echo "[deskwise] or set API_PORT / WEB_PORT (plus NEXT_PUBLIC_API_URL, CORS_ALLOWED_ORIGINS," >&2
    echo "[deskwise] CSRF_TRUSTED_ORIGINS, PUBLIC_BASE_URL to match) in .env and re-run." >&2
    exit 1
  fi
}

MODE="${1:-docker}"

case "$MODE" in
  --stop|stop)
    if [[ -x "$ROOT/stop.sh" ]]; then
      "$ROOT/stop.sh" || true
    elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
      docker compose down || true
    fi
    echo "[deskwise] Stopped local services."
    exit 0
    ;;

  --native|native)
    command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 (3.12+) is required for --native mode." >&2; exit 1; }
    command -v node >/dev/null 2>&1 || { echo "ERROR: node (20+) is required for --native mode." >&2; exit 1; }

    ensure_env_file "$ROOT/backend/.env" "$ROOT/backend/.env.example"

    if [[ ! -x "$ROOT/backend/.venv/bin/python" ]]; then
      echo "[deskwise] Creating Python virtualenv at backend/.venv ..."
      python3 -m venv "$ROOT/backend/.venv"
    fi
    echo "[deskwise] Installing Python dependencies ..."
    "$ROOT/backend/.venv/bin/pip" install -q -r "$ROOT/backend/requirements.txt"

    echo "[deskwise] Installing Frontend dependencies ..."
    if command -v pnpm >/dev/null 2>&1; then
      (cd "$ROOT/frontend" && pnpm install --frozen-lockfile)
    elif command -v corepack >/dev/null 2>&1; then
      (cd "$ROOT/frontend" && corepack pnpm install --frozen-lockfile)
    else
      (cd "$ROOT/frontend" && npm install)
    fi

    echo "[deskwise] Running migrations & seeding demo workspace ..."
    mkdir -p "$ROOT/.dev-logs"
    CREDS_FILE="$ROOT/.dev-logs/demo-credentials.txt"
    if [[ -f "$CREDS_FILE" ]]; then
      DEMO_PASS="$(grep '^Password:' "$CREDS_FILE" | awk '{print $2}' || true)"
    fi
    DEMO_PASS="${DEMO_PASS:-$(gen_demo_password)}"

    (
      cd "$ROOT/backend"
      ./.venv/bin/python manage.py migrate --noinput
      ./.venv/bin/python manage.py seed_plans
      ./.venv/bin/python manage.py seed_policy_docs \
        --email demo@deskwise.test \
        --password "$DEMO_PASS" \
        --skip-embeddings
    )
    printf "Email:    demo@deskwise.test\nPassword: %s\n" "$DEMO_PASS" > "$CREDS_FILE"
    chmod 600 "$CREDS_FILE"

    "$ROOT/start.sh" --native
    ;;

  --docker|docker|"")
    command -v docker >/dev/null 2>&1 || {
      echo "ERROR: Docker is not installed. Install Docker Desktop / Engine, or run: ./scripts/start_local.sh --native" >&2
      exit 1
    }
    docker compose version >/dev/null 2>&1 || {
      echo "ERROR: 'docker compose' v2 plugin is required." >&2
      exit 1
    }

    ensure_env_file "$ROOT/.env" "$ROOT/.env.example"

    API_PORT="$(env_value "$ROOT/.env" API_PORT 8000)"
    WEB_PORT="$(env_value "$ROOT/.env" WEB_PORT 3000)"
    # Only check when our own stack is not already running (re-runs are fine).
    if [[ -z "$(docker compose ps -q 2>/dev/null)" ]]; then
      check_ports "$API_PORT" "$WEB_PORT"
    fi

    echo "[deskwise] Building and starting Docker containers (api + web) ..."
    docker compose up -d --build --wait

    echo "[deskwise] Running database migrations ..."
    docker compose exec -T api python manage.py migrate --noinput
    docker compose exec -T api python manage.py seed_plans

    mkdir -p "$ROOT/.dev-logs"
    CREDS_FILE="$ROOT/.dev-logs/demo-credentials.txt"
    if [[ -f "$CREDS_FILE" ]]; then
      DEMO_PASS="$(grep '^Password:' "$CREDS_FILE" | awk '{print $2}' || true)"
    fi
    DEMO_PASS="${DEMO_PASS:-$(gen_demo_password)}"

    echo "[deskwise] Seeding demo company & HR policy/template corpus ..."
    docker compose exec -T api python manage.py seed_policy_docs \
      --email demo@deskwise.test \
      --password "$DEMO_PASS" \
      --skip-embeddings
    printf "Email:    demo@deskwise.test\nPassword: %s\n" "$DEMO_PASS" > "$CREDS_FILE"
    chmod 600 "$CREDS_FILE"

    wait_for_url "http://localhost:${API_PORT}/api/health" "Django API" 45
    wait_for_url "http://localhost:${WEB_PORT}" "Next.js Web" 45
    ;;

  *)
    echo "Usage: $0 [--docker | --native | --stop]" >&2
    exit 2
    ;;
esac

cat <<EOF

========================================================================
  Deskwise is LIVE locally!
------------------------------------------------------------------------
  Web App:       http://localhost:${WEB_PORT:-3000}
  API Health:    http://localhost:${API_PORT:-8000}/api/health
  Demo Admin:    demo@deskwise.test
  Demo Password: ${DEMO_PASS}
  (Saved locally in .dev-logs/demo-credentials.txt — gitignored)

  Stop anytime:  ./scripts/start_local.sh --stop
========================================================================
EOF
