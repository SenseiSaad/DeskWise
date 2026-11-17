#!/usr/bin/env bash
# ==============================================================================
# Deskwise — Unified Start Script (Frontend, Backend, WebSockets, DB)
#
# Usage:
#   ./start.sh              Smart fast start (rebuilds only changed images, then
#                           swaps containers and prunes replaced <none> images)
#   ./start.sh --rebuild    Force rebuild + remove old unused/stale images after
#                           the new containers are up (keeps layer cache safely)
#   ./start.sh --fresh      Force full --no-cache rebuild + remove old images
#   ./start.sh --docker     Force Docker Compose mode (:3000 Web, :8000 API, DB)
#   ./start.sh --native     Start local host servers (uvicorn ASGI + Next.js,
#                           plus Docker Postgres DB if --pg or postgres URL)
#   ./start.sh --pg         Enable PostgreSQL + pgvector database container
#   ./start.sh --redis      Enable Redis container (multi-worker channel layer)
#   ./start.sh --build      Force rebuilding Docker images (keep layer cache)
#   ./start.sh --no-build   Never rebuild Docker images if they already exist
#   ./start.sh --migrate    Force running Django migrations & seed_plans
#   ./start.sh --open       Open http://localhost:3000 in browser when ready
#
# Stop everything cleanly with: ./stop.sh
# ==============================================================================
set -euo pipefail

export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/.dev-logs"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
APP_ICON="$FRONTEND_DIR/public/openvault-logo-300.png"

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
FORCE_BUILD=0
PRUNE_OLD=0
NO_CACHE=0
NO_BUILD=0
FORCE_MIGRATE=0
OPEN_BROWSER=0
GUI_MODE=0

for arg in "$@"; do
  case "$arg" in
    --docker|docker) MODE="docker" ;;
    --native|native) MODE="native" ;;
    --pg) USE_PG=1 ;;
    --redis) USE_REDIS=1 ;;
    --build) FORCE_BUILD=1 ;;
    --rebuild|--clean-build) FORCE_BUILD=1; PRUNE_OLD=1 ;;
    --fresh|--no-cache) FORCE_BUILD=1; PRUNE_OLD=1; NO_CACHE=1 ;;
    --no-build) NO_BUILD=1 ;;
    --migrate) FORCE_MIGRATE=1 ;;
    --open) OPEN_BROWSER=1 ;;
    --gui) GUI_MODE=1; OPEN_BROWSER=1 ;;
    -h|--help)
      sed -n '2,23p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (use --docker, --native, --pg, --redis, --build, --rebuild, --fresh, --no-build, --migrate, --open)" >&2
      exit 2
      ;;
  esac
done

if [[ "$GUI_MODE" == "1" ]]; then
  mkdir -p "$LOG_DIR"
  exec > "$LOG_DIR/launcher.log" 2>&1
  on_gui_exit() {
    local rc=$?
    if [[ "$rc" -ne 0 ]]; then
      if command -v notify-send >/dev/null 2>&1; then
        notify-send -u critical -a "Deskwise" -i "$APP_ICON" "Deskwise Failed to Start" "Check $LOG_DIR/launcher.log" >/dev/null 2>&1 || true
      fi
      if command -v kdialog >/dev/null 2>&1; then
        kdialog --error "Deskwise failed to start. See $LOG_DIR/launcher.log" >/dev/null 2>&1 || true
      fi
    fi
  }
  trap on_gui_exit EXIT
fi

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

# Local runs must never point at production infrastructure. Refuse to start if
# the env file looks like a live/prod config, so a local boot cannot write to the
# production database or S3 bucket.
assert_local_only() {
  local f="$1" dburl envv bucket bad=""
  [[ -f "$f" ]] || return 0
  dburl="$(env_val "$f" DATABASE_URL "")"
  envv="$(env_val "$f" ENVIRONMENT "")"
  bucket="$(env_val "$f" AWS_STORAGE_BUCKET_NAME "")"
  if [[ -n "$dburl" && ! "$dburl" =~ (localhost|127\.0\.0\.1|@db:|host\.docker\.internal|sqlite) ]]; then
    bad="DATABASE_URL points at a remote database"
  elif [[ "$envv" =~ ^(production|prod)$ ]]; then
    bad="ENVIRONMENT=$envv"
  elif [[ -n "$bucket" ]]; then
    bad="AWS_STORAGE_BUCKET_NAME is set (would write to real S3)"
  fi
  if [[ -n "$bad" ]]; then
    echo "[deskwise] REFUSING to start: $f looks like a PRODUCTION config ($bad)." >&2
    echo "[deskwise] Local runs must use a local database and local disk storage." >&2
    echo "[deskwise] Fix those values in $f, or set ENVIRONMENT=development and" >&2
    echo "[deskwise] leave DATABASE_URL / AWS_STORAGE_BUCKET_NAME unset locally." >&2
    exit 1
  fi
}

_read_aws_cred_file() {
  local cred_file="$1" section="$2" key="$3"
  [[ -f "$cred_file" ]] || return 1
  awk -v sec="[$section]" -v k="$key" '
    { line=$0; gsub(/^[[:space:]]+|[[:space:]]+$/, "", line) }
    substr(line, 1, 1) == "[" { in_sec = (line == sec) ? 1 : 0; next }
    in_sec && index(line, "=") > 0 {
      keypart = substr(line, 1, index(line, "=") - 1)
      gsub(/[[:space:]]+$/, "", keypart)
      if (keypart == k) {
        val = substr(line, index(line, "=") + 1)
        gsub(/^[[:space:]]+|[[:space:]]*(#.*)?$/, "", val)
        print val
        exit
      }
    }
  ' "$cred_file"
}

load_bedrock_aws_creds() {
  local env_file="$1"
  local bedrock_key_val bedrock_prof target_sec cred_file ak sk st aws_creds
  bedrock_key_val="$(env_val "$env_file" BEDROCK_API_KEY "")"
  bedrock_prof="${BEDROCK_AWS_PROFILE:-$(env_val "$env_file" BEDROCK_AWS_PROFILE "")}"
  if [[ -z "${AWS_ACCESS_KEY_ID:-}" && -z "$bedrock_key_val" ]]; then
    target_sec="${bedrock_prof:-${AWS_PROFILE:-default}}"
    cred_file="${AWS_SHARED_CREDENTIALS_FILE:-$HOME/.aws/credentials}"
    ak="$(_read_aws_cred_file "$cred_file" "$target_sec" "aws_access_key_id" || true)"
    sk="$(_read_aws_cred_file "$cred_file" "$target_sec" "aws_secret_access_key" || true)"
    st="$(_read_aws_cred_file "$cred_file" "$target_sec" "aws_session_token" || true)"
    if [[ -n "$ak" && -n "$sk" ]]; then
      export AWS_ACCESS_KEY_ID="$ak" AWS_SECRET_ACCESS_KEY="$sk"
      [[ -n "$st" ]] && export AWS_SESSION_TOKEN="$st"
      if [[ -z "${AWS_DEFAULT_REGION:-}" ]]; then
        AWS_DEFAULT_REGION="$(env_val "$env_file" BEDROCK_REGION "")"
        if [[ -z "$AWS_DEFAULT_REGION" ]]; then
          local cfg_sec cfg_file
          cfg_file="${AWS_CONFIG_FILE:-$HOME/.aws/config}"
          cfg_sec="$([[ "$target_sec" == "default" ]] && echo "default" || echo "profile $target_sec")"
          AWS_DEFAULT_REGION="$(_read_aws_cred_file "$cfg_file" "$cfg_sec" "region" || true)"
          AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
        fi
        export AWS_DEFAULT_REGION
      fi
      echo "[deskwise] Loaded AWS CLI credentials for Bedrock${bedrock_prof:+ (profile: $bedrock_prof)} (${AWS_DEFAULT_REGION})."
    elif command -v aws >/dev/null 2>&1; then
      local aws_export_cmd=(aws configure export-credentials --format env)
      [[ -n "$bedrock_prof" ]] && aws_export_cmd+=(--profile "$bedrock_prof")
      if aws_creds="$("${aws_export_cmd[@]}" 2>/dev/null)" && [[ -n "$aws_creds" ]]; then
        eval "$aws_creds"
        export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
        if [[ -z "${AWS_DEFAULT_REGION:-}" ]]; then
          AWS_DEFAULT_REGION="$(env_val "$env_file" BEDROCK_REGION "")"
          if [[ -z "$AWS_DEFAULT_REGION" ]]; then
            local region_cmd=(aws configure get region)
            [[ -n "$bedrock_prof" ]] && region_cmd+=(--profile "$bedrock_prof")
            AWS_DEFAULT_REGION="$("${region_cmd[@]}" 2>/dev/null || echo us-east-1)"
          fi
          export AWS_DEFAULT_REGION
        fi
        echo "[deskwise] Loaded AWS CLI credentials for Bedrock${bedrock_prof:+ (profile: $bedrock_prof)} (${AWS_DEFAULT_REGION})."
      fi
    fi
  fi
}

ensure_env() {
  local target="$1" template="$2"
  if [[ ! -f "$target" ]]; then
    cp "$template" "$target"
    echo "[deskwise] Created $target from $template"
  fi
  if grep -qE '^SECRET_KEY=\s*$' "$target" || ! grep -qE '^SECRET_KEY=' "$target"; then
    local sk; sk="$(gen_secret)"
    sed -i.bak '/^SECRET_KEY=/d' "$target" && rm -f "${target}.bak"
    printf '\nSECRET_KEY=%s\n' "$sk" >> "$target"
    echo "[deskwise] Generated SECRET_KEY in $target"
  fi
  if grep -qE '^LLM_KEY_ENCRYPTION_KEY=\s*$' "$target" || ! grep -qE '^LLM_KEY_ENCRYPTION_KEY=' "$target"; then
    local lk; lk="$(gen_secret)"
    sed -i.bak '/^LLM_KEY_ENCRYPTION_KEY=/d' "$target" && rm -f "${target}.bak"
    printf 'LLM_KEY_ENCRYPTION_KEY=%s\n' "$lk" >> "$target"
    echo "[deskwise] Generated LLM_KEY_ENCRYPTION_KEY in $target"
  fi
  # docker-compose.yml validates services.db POSTGRES_PASSWORD even when --profile pg is inactive.
  local cur_pg_pass
  cur_pg_pass="$(env_val "$target" POSTGRES_PASSWORD "")"
  if [[ -z "$cur_pg_pass" || "$cur_pg_pass" == "replace-with-secure-db-password" ]]; then
    local pg_pw; pg_pw="$(gen_secret)"
    sed -i.bak '/^#\?\s*POSTGRES_PASSWORD=/d' "$target" && rm -f "${target}.bak"
    printf 'POSTGRES_PASSWORD=%s\n' "$pg_pw" >> "$target"
    echo "[deskwise] Set POSTGRES_PASSWORD in $target for Compose validation"
  fi
}

wait_for_url() {
  local url="$1" label="$2" timeout_s="${3:-45}"
  local max_tries=$(( timeout_s * 6 ))
  for ((i = 1; i <= max_tries; i++)); do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      echo "[deskwise] $label ready -> $url"
      return 0
    fi
    sleep 0.15
  done
  echo "[deskwise] ERROR: Timed out waiting for $label at $url" >&2
  return 1
}

wait_all_ready() {
  local api_port="$1" web_port="$2" timeout_s="${3:-45}"
  local pid_api pid_web rc=0
  wait_for_url "http://127.0.0.1:${api_port}/api/health" "Backend API" "$timeout_s" &
  pid_api=$!
  wait_for_url "http://127.0.0.1:${web_port}" "Frontend Web" "$timeout_s" &
  pid_web=$!
  wait "$pid_api" || rc=1
  wait "$pid_web" || rc=1
  return "$rc"
}

boot_stamp_hash() {
  local db_key="$1"
  {
    printf '%s\n' "$db_key"
    cat "$BACKEND_DIR"/core/migrations/*.py "$BACKEND_DIR"/core/management/commands/seed_plans.py 2>/dev/null || true
  } | { sha256sum 2>/dev/null || shasum -a 256 2>/dev/null || cksum; } | awk '{print $1}'
}

needs_image_build() {
  local svc="$1" img="$2" src_dir="$3"
  local stamp="$LOG_DIR/.docker_build_${svc}.stamp"
  local img_created changed
  img_created="$(docker image inspect -f '{{.Created}}' "$img" 2>/dev/null || true)"
  if [[ -z "$img_created" ]]; then
    return 0
  fi
  if [[ "$NO_BUILD" == "1" ]]; then
    return 1
  fi
  if [[ "$FORCE_BUILD" == "1" ]]; then
    return 0
  fi
  if [[ ! -f "$stamp" ]]; then
    touch -d "$img_created" "$stamp" 2>/dev/null || return 0
  fi
  if [[ "$ROOT/docker-compose.yml" -nt "$stamp" ]]; then
    return 0
  fi
  changed="$(
    find "$ROOT/$src_dir" -maxdepth 6 \
      \( -name .venv -o -name node_modules -o -name .next -o -name out -o -name __pycache__ -o -name .git -o -name .pytest_cache -o -name htmlcov -o -name media -o -name '*.sqlite3*' -o -name '*.pyc' -o -name '.coverage*' -o -name '*.tsbuildinfo' -o -name '.env*' -o -name '*.log' \) -prune \
      -o -type f -newer "$stamp" -print -quit 2>/dev/null || true
  )"
  [[ -n "$changed" ]]
}

# Stop and remove containers from other Compose projects holding our ports so we never serve a stale copy.
stop_conflicting_containers() {
  local port cid own_cids stale_c
  own_cids="$(docker compose ps -a -q 2>/dev/null || true)"
  for port in "$@"; do
    for cid in $(docker ps --filter "publish=${port}" -q 2>/dev/null || true); do
      if [[ -z "$own_cids" ]] || ! printf '%s\n' "$own_cids" | grep -q "^${cid}"; then
        local cname
        cname="$(docker inspect -f '{{.Name}}' "$cid" 2>/dev/null | sed 's|^/||' || echo "$cid")"
        echo "[deskwise] Stopping conflicting container on :${port} (${cname}) ..."
        docker rm -f "$cid" >/dev/null 2>&1 || true
      fi
    done
  done
  for stale_c in openvault_audit_copy-web-1 openvault_audit_copy-api-1; do
    if docker inspect "$stale_c" >/dev/null 2>&1; then
      docker rm -f "$stale_c" >/dev/null 2>&1 || true
    fi
  done
}

# Safe post-build cleanup: always prune replaced <none> dangling layers and unused legacy images.
cleanup_old_images() {
  echo "[deskwise] Pruning replaced dangling Docker images ..."
  docker image prune -f >/dev/null 2>&1 || true
  local stale_img
  for stale_img in openvault_audit_copy-api:latest openvault_audit_copy-web:latest openvault-api:drill openvault-web:drill; do
    if docker image inspect "$stale_img" >/dev/null 2>&1; then
      if [[ -z "$(docker ps -a --filter "ancestor=$stale_img" -q 2>/dev/null || true)" ]]; then
        echo "[deskwise] Removing stale image: $stale_img"
        docker rmi "$stale_img" >/dev/null 2>&1 || true
      fi
    fi
  done
  if [[ "$PRUNE_OLD" == "1" ]]; then
    docker builder prune -f --filter "until=72h" >/dev/null 2>&1 || true
  fi
}

notify_desktop() {
  local title="$1" body="$2"
  if command -v notify-send >/dev/null 2>&1 && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    notify-send -a "Deskwise" -i "$APP_ICON" "$title" "$body" >/dev/null 2>&1 || true
  fi
}

open_browser() {
  local url="$1"
  if [[ "$OPEN_BROWSER" == "1" ]] && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    if command -v xdg-open >/dev/null 2>&1; then
      nohup xdg-open "$url" >/dev/null 2>&1 < /dev/null &
    elif command -v google-chrome >/dev/null 2>&1; then
      nohup google-chrome "$url" >/dev/null 2>&1 < /dev/null &
    fi
  fi
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
  assert_local_only "$ROOT/.env"

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

  # Clear any leftover native dev processes so host ports are free for Docker.
  if [[ -f "$LOG_DIR/backend.pid" || -f "$LOG_DIR/frontend.pid" ]]; then
    "$ROOT/stop.sh" --native >/dev/null 2>&1 || true
  fi
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

  load_bedrock_aws_creds "$ROOT/.env"

  stop_conflicting_containers "$API_PORT" "$WEB_PORT"

  REBUILT=0
  if [[ "$NO_BUILD" == "0" ]]; then
    BUILD_ARGS=()
    [[ "$NO_CACHE" == "1" ]] && BUILD_ARGS+=(--no-cache)
    echo "[deskwise] Building latest Docker images (api web) ..."
    docker compose build "${BUILD_ARGS[@]}" api web
    touch "$LOG_DIR/.docker_build_api.stamp" "$LOG_DIR/.docker_build_web.stamp"
    REBUILT=1
  fi

  echo "[deskwise] Starting fresh Docker containers (${PROFILES[*]:-SQLite + API + Web}) ..."
  export AUTO_MIGRATE=false
  if (( ${#PROFILES[@]} > 0 )); then
    docker compose "${PROFILES[@]}" up -d --no-build --force-recreate --remove-orphans
  else
    docker compose up -d --no-build --force-recreate --remove-orphans
  fi

  if [[ "$REBUILT" == "1" || "$PRUNE_OLD" == "1" ]]; then
    cleanup_old_images
  fi

  BOOT_HASH="$(boot_stamp_hash "${PG_DB}|${PG_HOST}|${DB_URL}")"
  if [[ "$FORCE_MIGRATE" == "1" ]] || ! docker compose exec -T api sh -c \
    'test -f /app/data/.deskwise_boot_stamp && [ "$(cat /app/data/.deskwise_boot_stamp)" = "'"$BOOT_HASH"'" ]' \
    >/dev/null 2>&1; then
    echo "[deskwise] Running migrations & seeding plans ..."
    docker compose exec -T api sh -c \
      'python manage.py migrate --noinput && python manage.py seed_plans && printf "%s" "'"$BOOT_HASH"'" > /app/data/.deskwise_boot_stamp'
  fi

  wait_all_ready "$API_PORT" "$WEB_PORT" 45
  touch "$LOG_DIR/.docker_running.stamp"

  echo
  echo "Deskwise is running (Docker): Web http://localhost:${WEB_PORT} | API http://localhost:${API_PORT}"
  echo "Stop all servers anytime with: ./stop.sh"
  notify_desktop "Deskwise Started" "Web & API are ready at http://localhost:${WEB_PORT}"
  open_browser "http://localhost:${WEB_PORT}"
  exit 0
fi

# ------------------------------------------------------------------------------
# Native Host Mode (Python ASGI WebSockets + Next.js + optional Docker PG DB)
# ------------------------------------------------------------------------------
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required for native mode." >&2; exit 1; }
command -v node >/dev/null 2>&1 || { echo "ERROR: node is required for native mode." >&2; exit 1; }

ensure_env "$BACKEND_DIR/.env" "$BACKEND_DIR/.env.example"
assert_local_only "$BACKEND_DIR/.env"
mkdir -p "$LOG_DIR"

API_PORT="$(env_val "$BACKEND_DIR/.env" API_PORT 8000)"
WEB_PORT="$(env_val "$BACKEND_DIR/.env" WEB_PORT 3000)"
DB_URL="$(env_val "$BACKEND_DIR/.env" DATABASE_URL "")"

if [[ "$USE_PG" == "1" ]] || [[ "$DB_URL" == postgres* ]]; then
  docker_available || { echo "ERROR: PostgreSQL requested but Docker is unavailable." >&2; exit 1; }
  ensure_env "$ROOT/.env" "$ROOT/.env.example"
  assert_local_only "$ROOT/.env"
  echo "[deskwise] Starting PostgreSQL database container ..."
  docker compose --profile pg up -d --wait db
fi

PY="$BACKEND_DIR/.venv/bin/python"
UVICORN="$BACKEND_DIR/.venv/bin/uvicorn"
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

NATIVE_BOOT_STAMP="$LOG_DIR/.native_boot.stamp"
NATIVE_BOOT_HASH="$(boot_stamp_hash "native|${DB_URL}|${USE_PG}")"
if [[ "$FORCE_MIGRATE" == "1" ]] \
  || [[ ! -f "$NATIVE_BOOT_STAMP" ]] \
  || [[ "$(cat "$NATIVE_BOOT_STAMP" 2>/dev/null || true)" != "$NATIVE_BOOT_HASH" ]] \
  || [[ -z "$DB_URL" && ! -f "$BACKEND_DIR/db.sqlite3" ]]; then
  echo "[deskwise] Running database migrations & seeding plans ..."
  (
    cd "$BACKEND_DIR"
    "$PY" manage.py migrate --noinput
    "$PY" manage.py seed_plans
  )
  printf '%s' "$NATIVE_BOOT_HASH" > "$NATIVE_BOOT_STAMP"
fi

echo "[deskwise] Starting Backend ASGI API + WebSockets on :${API_PORT} ..."
load_bedrock_aws_creds "$BACKEND_DIR/.env"
if [[ -x "$UVICORN" ]]; then
  (
    cd "$BACKEND_DIR"
    setsid nohup "$UVICORN" config.asgi:application \
      --host 0.0.0.0 --port "${API_PORT}" \
      > "$LOG_DIR/backend.log" 2>&1 < /dev/null &
    echo $! > "$LOG_DIR/backend.pid"
  )
elif "$PY" -c "import uvicorn" >/dev/null 2>&1; then
  (
    cd "$BACKEND_DIR"
    setsid nohup "$PY" -m uvicorn config.asgi:application \
      --host 0.0.0.0 --port "${API_PORT}" \
      > "$LOG_DIR/backend.log" 2>&1 < /dev/null &
    echo $! > "$LOG_DIR/backend.pid"
  )
elif [[ -x "$GUNICORN" ]]; then
  (
    cd "$BACKEND_DIR"
    setsid nohup "$GUNICORN" config.asgi:application -k uvicorn_worker.UvicornWorker \
      --bind "0.0.0.0:${API_PORT}" --workers 1 --timeout 180 \
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

wait_all_ready "$API_PORT" "$WEB_PORT" 60

echo
echo "Deskwise is running (Native): Web http://localhost:${WEB_PORT} | API http://localhost:${API_PORT}"
echo "Logs: $LOG_DIR/backend.log | $LOG_DIR/frontend.log"
echo "Stop all servers anytime with: ./stop.sh"
notify_desktop "Deskwise Started" "Web & API are ready at http://localhost:${WEB_PORT}"
open_browser "http://localhost:${WEB_PORT}"
