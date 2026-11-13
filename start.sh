#!/usr/bin/env bash
# ==============================================================================
# Deskwise — Unified Start Script (Frontend, Backend, and Database if needed)
#
# Usage:
#   ./start.sh              Start via Docker Compose (default when Docker is up;
#                           auto-enables Postgres/Redis profiles when configured)
#   ./start.sh --docker     Force Docker Compose mode (:3000 Web, :8000 API, DB)
#   ./start.sh --native     Start local host servers (gunicorn/runserver + Next.js,
#                           plus Docker Postgres DB if --pg or postgres URL is set)
#   ./start.sh --pg         Enable PostgreSQL + pgvector database container
#   ./start.sh --redis      Enable Redis container
#
# Stop everything cleanly with: ./stop.sh
# ==============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/.dev-logs"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"

# Load Node version managers cleanly if present on the machine
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
export VOLTA_HOME="${VOLTA_HOME:-$HOME/.volta}"
[ -s "$VOLTA_HOME/bin" ] && export PATH="$VOLTA_HOME/bin:$PATH"
if [ -s "$HOME/.local/share/fnm/fnm" ]; then
  export PATH="$HOME/.local/share/fnm:$PATH"
  eval "$("$HOME/.local/share/fnm/fnm" env)"
fi

MODE="auto"
USE_PG=0
USE_REDIS=0

for arg in "$@"; do
  case "$arg" in
    --docker|docker) MODE="docker" ;;
    --native|native) MODE="native" ;;
    --pg) USE_PG=1 ;;
    --redis) USE_REDIS=1 ;;
    -h|--help)
      sed -n '2,15p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (use --docker, --native, --pg, --redis)" >&2
      exit 2
      ;;
  esac
done

gen_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 48 | tr '+/' '-_' | tr -d '=\n'
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
  else
    head -c 48 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n'
  fi
}

env_val() {
  local v
  v="$(grep -E "^$2=" "$1" 2>/dev/null | tail -1 | cut -d= -f2- || true)"
  echo "${v:-$3}"
}

load_bedrock_aws_creds() {
  local env_file="$1"
  local bedrock_key_val bedrock_prof aws_creds
  bedrock_key_val="$(env_val "$env_file" BEDROCK_API_KEY "")"
  bedrock_prof="${BEDROCK_AWS_PROFILE:-$(env_val "$env_file" BEDROCK_AWS_PROFILE "")}"
  if [[ -z "${AWS_ACCESS_KEY_ID:-}" && -z "$bedrock_key_val" ]] && command -v aws >/dev/null 2>&1; then
    local aws_export_cmd=(aws configure export-credentials --format env)
    [[ -n "$bedrock_prof" ]] && aws_export_cmd+=(--profile "$bedrock_prof")
    if aws_creds="$("${aws_export_cmd[@]}" 2>/dev/null)" && [[ -n "$aws_creds" ]]; then
      eval "$aws_creds"
      export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
      if [[ -z "${AWS_DEFAULT_REGION:-}" ]]; then
        local region_cmd=(aws configure get region)
        [[ -n "$bedrock_prof" ]] && region_cmd+=(--profile "$bedrock_prof")
        AWS_DEFAULT_REGION="$(env_val "$env_file" BEDROCK_REGION "$("${region_cmd[@]}" 2>/dev/null || echo us-east-1)")"
        export AWS_DEFAULT_REGION
      fi
      echo "[deskwise] Loaded AWS CLI credentials for Bedrock${bedrock_prof:+ (profile: $bedrock_prof)} (${AWS_DEFAULT_REGION})."
    fi
  fi
}

ensure_env() {
  local target="$1" template="$2"
  if [[ ! -f "$target" ]]; then
    cp "$template" "$target"
    echo "[deskwise] Created $target from $template"
  fi
  if grep -qE '^SECRET_KEY=\s*$' "$target"; then
    local sk; sk="$(gen_secret)"
    sed -i.bak "s|^SECRET_KEY=.*|SECRET_KEY=${sk}|" "$target" && rm -f "${target}.bak"
    echo "[deskwise] Generated SECRET_KEY in $target"
  fi
  if grep -qE '^LLM_KEY_ENCRYPTION_KEY=\s*$' "$target"; then
    local lk; lk="$(gen_secret)"
    sed -i.bak "s|^LLM_KEY_ENCRYPTION_KEY=.*|LLM_KEY_ENCRYPTION_KEY=${lk}|" "$target" && rm -f "${target}.bak"
    echo "[deskwise] Generated LLM_KEY_ENCRYPTION_KEY in $target"
  fi
}

wait_for_url() {
  local url="$1" label="$2" tries="${3:-45}"
  for ((i = 1; i <= tries; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "[deskwise] $label ready -> $url"
      return 0
    fi
    sleep 1
  done
  echo "[deskwise] ERROR: Timed out waiting for $label at $url" >&2
  return 1
}

native_watch_ok() {
  command -v node >/dev/null 2>&1 || return 1
  node -e "try{require('fs').watch(process.cwd(),function(){}).close();process.exit(0)}catch(e){process.exit(1)}" >/dev/null 2>&1
}

docker_available() {
  command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 && docker info >/dev/null 2>&1
}

if [[ "$MODE" == "auto" ]]; then
  if docker_available; then
    MODE="docker"
  else
    MODE="native"
    echo "[deskwise] Docker daemon unavailable — starting in native host mode."
  fi
fi

# ------------------------------------------------------------------------------
# Docker Compose Mode (API + Web + optional PostgreSQL/pgvector & Redis)
# ------------------------------------------------------------------------------
if [[ "$MODE" == "docker" ]]; then
  docker_available || {
    echo "[deskwise] ERROR: Docker daemon is not reachable. Start Docker or run ./start.sh --native" >&2
    exit 1
  }

  ensure_env "$ROOT/.env" "$ROOT/.env.example"

  API_PORT="$(env_val "$ROOT/.env" API_PORT 8000)"
  WEB_PORT="$(env_val "$ROOT/.env" WEB_PORT 3000)"
  PG_DB="$(env_val "$ROOT/.env" POSTGRES_DB "")"
  PG_USER="$(env_val "$ROOT/.env" POSTGRES_USER "")"
  PG_PASS="$(env_val "$ROOT/.env" POSTGRES_PASSWORD "")"
  PG_HOST="$(env_val "$ROOT/.env" POSTGRES_HOST "")"
  DB_URL="$(env_val "$ROOT/.env" DATABASE_URL "")"
  CACHE_VAL="$(env_val "$ROOT/.env" CACHE_URL "")"
  REDIS_VAL="$(env_val "$ROOT/.env" REDIS_URL "")"

  PROFILES=()
  if [[ "$USE_PG" == "1" ]] || [[ -n "$PG_DB" ]] || [[ -n "$PG_HOST" ]] || [[ "$DB_URL" == postgres* ]]; then
    if [[ -z "$PG_DB" ]]; then
      PG_DB="deskwise"
      sed -i.bak '/^#\?\s*POSTGRES_DB=/d' "$ROOT/.env" && rm -f "$ROOT/.env.bak"
      printf '\nPOSTGRES_DB=%s\n' "$PG_DB" >> "$ROOT/.env"
    fi
    if [[ -z "$PG_USER" ]]; then
      PG_USER="deskwise_user"
      sed -i.bak '/^#\?\s*POSTGRES_USER=/d' "$ROOT/.env" && rm -f "$ROOT/.env.bak"
      printf 'POSTGRES_USER=%s\n' "$PG_USER" >> "$ROOT/.env"
    fi
    if [[ -z "$PG_PASS" || "$PG_PASS" == "replace-with-secure-db-password" ]]; then
      PG_PASS="$(gen_secret)"
      sed -i.bak '/^#\?\s*POSTGRES_PASSWORD=/d' "$ROOT/.env" && rm -f "$ROOT/.env.bak"
      printf 'POSTGRES_PASSWORD=%s\n' "$PG_PASS" >> "$ROOT/.env"
      echo "[deskwise] Generated POSTGRES_PASSWORD in .env for PostgreSQL container."
    fi
    if [[ -z "$PG_HOST" ]]; then
      sed -i.bak '/^#\?\s*POSTGRES_HOST=/d' "$ROOT/.env" && rm -f "$ROOT/.env.bak"
      printf 'POSTGRES_HOST=db\n' >> "$ROOT/.env"
    fi
    PROFILES+=(--profile pg)
  fi
  if [[ "$USE_REDIS" == "1" ]] || [[ -n "$CACHE_VAL" ]] || [[ -n "$REDIS_VAL" ]]; then
    if [[ -z "$CACHE_VAL" && -z "$REDIS_VAL" ]]; then
      sed -i.bak '/^#\?\s*CACHE_URL=/d' "$ROOT/.env" && rm -f "$ROOT/.env.bak"
      printf '\nCACHE_URL=redis://redis:6379/0\n' >> "$ROOT/.env"
    fi
    PROFILES+=(--profile redis)
  fi

  # Clear any native dev processes so host ports :8000/:3000 are free for Docker.
  "$ROOT/stop.sh" --native >/dev/null 2>&1 || true
  mkdir -p "$LOG_DIR"

  # Forward local loopback Ollama (127.0.0.1:11434) onto the Docker bridge gateway
  # if Ollama isn't already bound on 0.0.0.0, so Docker `api` can reach host Ollama.
  GW_IP="$(docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || ip -4 -o addr show docker0 2>/dev/null | awk '{print $4}' | cut -d/ -f1 || echo 172.17.0.1)"
  if command -v python3 >/dev/null 2>&1 && ss -ltn 2>/dev/null | awk '{print $4}' | grep -q '^127\.0\.0\.1:11434$'; then
    if ! ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "(\\*|0\\.0\\.0\\.0|${GW_IP}):11434$"; then
      if [[ -f "$LOG_DIR/ollama-bridge.pid" ]] && kill -0 "$(cat "$LOG_DIR/ollama-bridge.pid" 2>/dev/null || true)" 2>/dev/null; then
        true
      else
        setsid nohup env GW_IP="$GW_IP" python3 -c '
import asyncio, os
gw, port = os.environ["GW_IP"], 11434
async def pipe(r, w):
    try:
        while data := await r.read(65536):
            w.write(data)
            await w.drain()
    except Exception:
        pass
    finally:
        try: w.close()
        except Exception: pass
async def handle(cr, cw):
    try:
        sr, sw = await asyncio.open_connection("127.0.0.1", port)
    except Exception:
        try: cw.close()
        except Exception: pass
        return
    await asyncio.gather(pipe(cr, sw), pipe(sr, cw))
async def main():
    srv = await asyncio.start_server(handle, gw, port)
    async with srv:
        await srv.serve_forever()
asyncio.run(main())
' > "$LOG_DIR/ollama-bridge.log" 2>&1 < /dev/null &
        echo $! > "$LOG_DIR/ollama-bridge.pid"
        echo "[deskwise] Bridged local Ollama (127.0.0.1:11434 -> ${GW_IP}:11434) for Docker."
      fi
    fi
  fi

  # Pass configured AWS CLI credentials into container runtime in memory only
  # (never written into .env or disk files). Supports BEDROCK_AWS_PROFILE to keep
  # the Bedrock AWS account separate from AWS_PROFILE used for infra/deploy.
  load_bedrock_aws_creds "$ROOT/.env"

  echo "[deskwise] Starting Docker stack (${PROFILES[*]:-SQLite + API + Web}) ..."
  docker compose "${PROFILES[@]}" up -d --build --wait

  echo "[deskwise] Running migrations & seeding plans ..."
  docker compose exec -T api python manage.py migrate --noinput
  docker compose exec -T api python manage.py seed_plans

  wait_for_url "http://localhost:${API_PORT}/api/health" "Backend API" 45
  wait_for_url "http://localhost:${WEB_PORT}" "Frontend Web" 45

  echo
  echo "Deskwise is running (Docker): Web http://localhost:${WEB_PORT} | API http://localhost:${API_PORT}"
  echo "Stop all servers anytime with: ./stop.sh"
  exit 0
fi

# ------------------------------------------------------------------------------
# Native Host Mode (Python backend + Next.js frontend + optional Docker PG DB)
# ------------------------------------------------------------------------------
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required for native mode." >&2; exit 1; }
command -v node >/dev/null 2>&1 || { echo "ERROR: node is required for native mode." >&2; exit 1; }

ensure_env "$BACKEND_DIR/.env" "$BACKEND_DIR/.env.example"
mkdir -p "$LOG_DIR"

API_PORT="$(env_val "$BACKEND_DIR/.env" API_PORT 8000)"
WEB_PORT="$(env_val "$BACKEND_DIR/.env" WEB_PORT 3000)"
DB_URL="$(env_val "$BACKEND_DIR/.env" DATABASE_URL "")"

if [[ "$USE_PG" == "1" ]] || [[ "$DB_URL" == postgres* ]]; then
  docker_available || { echo "ERROR: PostgreSQL requested but Docker is unavailable." >&2; exit 1; }
  ensure_env "$ROOT/.env" "$ROOT/.env.example"
  echo "[deskwise] Starting PostgreSQL database container ..."
  docker compose --profile pg up -d --wait db
fi

PY="$BACKEND_DIR/.venv/bin/python"
GUNICORN="$BACKEND_DIR/.venv/bin/gunicorn"
if [[ ! -x "$PY" ]]; then
  echo "[deskwise] Creating Python virtualenv at backend/.venv ..."
  python3 -m venv "$BACKEND_DIR/.venv"
  "$BACKEND_DIR/.venv/bin/pip" install -q -r "$BACKEND_DIR/requirements.txt"
fi

NEXT="$FRONTEND_DIR/node_modules/.bin/next"
if [[ ! -x "$NEXT" ]]; then
  echo "[deskwise] Installing frontend dependencies ..."
  if command -v pnpm >/dev/null 2>&1; then
    (cd "$FRONTEND_DIR" && pnpm install --frozen-lockfile)
  else
    (cd "$FRONTEND_DIR" && npm install)
  fi
fi

"$ROOT/stop.sh" --native >/dev/null 2>&1 || true

echo "[deskwise] Running database migrations & seeding plans ..."
(
  cd "$BACKEND_DIR"
  "$PY" manage.py migrate --noinput
  "$PY" manage.py seed_plans
)

echo "[deskwise] Starting Backend API on :${API_PORT} ..."
load_bedrock_aws_creds "$BACKEND_DIR/.env"
if [[ -x "$GUNICORN" ]]; then
  (
    cd "$BACKEND_DIR"
    setsid nohup "$GUNICORN" config.wsgi:application \
      --bind "0.0.0.0:${API_PORT}" --workers 1 --threads 8 --timeout 180 \
      > "$LOG_DIR/backend.log" 2>&1 < /dev/null &
    echo $! > "$LOG_DIR/backend.pid"
  )
else
  (
    cd "$BACKEND_DIR"
    setsid nohup "$PY" manage.py runserver "0.0.0.0:${API_PORT}" \
      > "$LOG_DIR/backend.log" 2>&1 < /dev/null &
    echo $! > "$LOG_DIR/backend.pid"
  )
fi

next_args=(dev -p "$WEB_PORT")
watch_env=()
if ! native_watch_ok; then
  echo "[deskwise] Linux inotify limit reached — starting Next.js with webpack polling."
  next_args+=(--webpack)
  watch_env=(WATCHPACK_POLLING=true CHOKIDAR_USEPOLLING=true)
fi

echo "[deskwise] Starting Frontend Web on :${WEB_PORT} ..."
(
  cd "$FRONTEND_DIR"
  setsid nohup env "${watch_env[@]}" "$NEXT" "${next_args[@]}" \
    > "$LOG_DIR/frontend.log" 2>&1 < /dev/null &
  echo $! > "$LOG_DIR/frontend.pid"
)

wait_for_url "http://localhost:${API_PORT}/api/health" "Backend API" 45
wait_for_url "http://localhost:${WEB_PORT}" "Frontend Web" 60

echo
echo "Deskwise is running (Native): Web http://localhost:${WEB_PORT} | API http://localhost:${API_PORT}"
echo "Logs: $LOG_DIR/backend.log | $LOG_DIR/frontend.log"
echo "Stop all servers anytime with: ./stop.sh"
