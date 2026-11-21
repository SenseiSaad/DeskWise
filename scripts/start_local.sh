#!/usr/bin/env bash
# ==============================================================================
# Deskwise — Cross-Platform One-Command Local Setup (Linux & macOS)
#
# Usage:
#   ./scripts/start_local.sh                        # Default: --no-ai (retrieval-only, zero keys)
#   ./scripts/start_local.sh doctor                 # Check Docker, Compose v2, ports, disk & RAM
#   ./scripts/start_local.sh --ai gemini            # Configure Google Gemini (key saved to gitignored .env)
#   ./scripts/start_local.sh --ai openai            # Configure OpenAI (key saved to gitignored .env)
#   ./scripts/start_local.sh --ai ollama            # Use host Ollama (http://host.docker.internal:11434)
#   ./scripts/start_local.sh --no-ai --no-browser   # Headless / CI mode
#   ./scripts/start_local.sh --stop                 # Stop local stack
#   ./scripts/start_local.sh --reset                # Stop stack + wipe local demo volumes & creds
# ==============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

AI_MODE="none"
NO_BROWSER=0
ACTION="start"

while [[ $# -gt 0 ]]; do
  case "$1" in
    doctor|--doctor) ACTION="doctor"; shift ;;
    --stop|stop) ACTION="stop"; shift ;;
    --reset|reset) ACTION="reset"; shift ;;
    --no-ai) AI_MODE="none"; shift ;;
    --ai)
      AI_MODE="${2:-}"
      if [[ ! "$AI_MODE" =~ ^(gemini|openai|ollama)$ ]]; then
        echo "[deskwise] ERROR: --ai must be one of: gemini, openai, ollama (never defaults to Bedrock)." >&2
        exit 2
      fi
      shift 2
      ;;
    --no-browser) NO_BROWSER=1; shift ;;
    -h|--help)
      sed -n '2,14p' "$0"
      exit 0
      ;;
    *)
      echo "[deskwise] Unknown argument: $1 (try --help)" >&2
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

gen_demo_password() {
  local suffix
  if command -v openssl >/dev/null 2>&1; then
    suffix="$(openssl rand -hex 6)"
  else
    suffix="$(head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  fi
  echo "DeskDemo!${suffix}9A"
}

set_env_kv() {
  local file="$1" key="$2" val="$3"
  if grep -qE "^${key}=" "$file" 2>/dev/null; then
    python3 - "$file" "$key" "$val" <<'PY'
import sys, pathlib
p, k, v = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lines = p.read_text(encoding="utf-8").splitlines()
out = [f"{k}={v}" if line.startswith(f"{k}=") else line for line in lines]
p.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
  else
    printf "%s=%s\n" "$key" "$val" >> "$file"
  fi
}

env_value() {
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

run_doctor() {
  local failed=0
  echo "=== Deskwise Local Environment Doctor ==="

  # 1. Docker CLI
  if command -v docker >/dev/null 2>&1; then
    echo "[PASS] Docker CLI installed ($(docker --version 2>/dev/null | head -n1))"
  else
    echo "[FAIL] Docker is not installed."
    echo "       Fix: Install Docker Desktop (macOS/Windows) or Docker Engine (Linux): https://docs.docker.com/get-docker/"
    failed=1
  fi

  # 2. Docker daemon running (no sudo needed)
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo "[PASS] Docker daemon is running and accessible without root"
  else
    echo "[FAIL] Docker daemon is not running or current user lacks socket access."
    echo "       Fix: Start Docker Desktop, or on Linux run: sudo usermod -aG docker \$USER && newgrp docker"
    echo "       Guide: https://docs.docker.com/engine/install/linux-postinstall/"
    failed=1
  fi

  # 3. Docker Compose v2
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    echo "[PASS] Docker Compose v2 available ($(docker compose version --short 2>/dev/null || echo 'v2'))"
  else
    echo "[FAIL] Docker Compose v2 plugin ('docker compose') not found."
    echo "       Fix: https://docs.docker.com/compose/install/"
    failed=1
  fi

  # 4. Ports 3000 & 8000 (skip warning if Deskwise stack is already up)
  local stack_running=""
  if command -v docker >/dev/null 2>&1; then
    stack_running="$(docker compose ps -q 2>/dev/null || true)"
  fi
  local api_port web_port
  api_port="$(env_value "$ROOT/.env" API_PORT 8000)"
  web_port="$(env_value "$ROOT/.env" WEB_PORT 3000)"
  for p in "$api_port" "$web_port"; do
    if [[ -n "$stack_running" ]]; then
      echo "[PASS] Port $p (Deskwise stack already running — idempotent restart allowed)"
    elif port_in_use "$p"; then
      echo "[FAIL] Port $p is already in use by another process."
      echo "       Fix: Stop the other service or set API_PORT/WEB_PORT in .env."
      failed=1
    else
      echo "[PASS] Port $p is free"
    fi
  done

  # 5. Disk space (>= 2 GB free)
  local avail_kb avail_gb
  avail_kb="$(df -k "$ROOT" | awk 'NR==2 {print $4}')"
  avail_gb=$(( avail_kb / 1024 / 1024 ))
  if (( avail_kb >= 2097152 )); then
    echo "[PASS] Disk space OK (${avail_gb} GB free, need >= 2 GB)"
  else
    echo "[FAIL] Low disk space (${avail_gb} GB free; recommend >= 2 GB for Docker images)"
    failed=1
  fi

  # 6. RAM (>= 2 GB total)
  local mem_mb=0
  if [[ -r /proc/meminfo ]]; then
    mem_mb="$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)"
  elif command -v sysctl >/dev/null 2>&1; then
    mem_mb="$(sysctl -n hw.memsize 2>/dev/null | awk '{printf "%d", $1/1024/1024}')"
  fi
  if (( mem_mb == 0 || mem_mb >= 2000 )); then
    echo "[PASS] System RAM OK (${mem_mb:-unknown} MB total)"
  else
    echo "[WARN] System RAM is ${mem_mb} MB (recommend >= 2048 MB for building containers)"
  fi

  if (( failed )); then
    echo "=== Doctor found issues above. Fix them and re-run. ==="
    return 1
  fi
  echo "=== Doctor passed! Ready to launch Deskwise. ==="
  return 0
}

ensure_env_file() {
  local target="$ROOT/.env"
  local template="$ROOT/.env.example"
  if [[ ! -f "$target" ]]; then
    cp "$template" "$target"
    echo "[deskwise] Created gitignored .env from .env.example"
  fi
  if grep -qE '^SECRET_KEY=\s*$' "$target" || ! grep -qE '^SECRET_KEY=' "$target"; then
    set_env_kv "$target" "SECRET_KEY" "$(gen_secret)"
    echo "[deskwise] Generated fresh local SECRET_KEY in .env"
  fi
  if grep -qE '^LLM_KEY_ENCRYPTION_KEY=\s*$' "$target" || ! grep -qE '^LLM_KEY_ENCRYPTION_KEY=' "$target"; then
    set_env_kv "$target" "LLM_KEY_ENCRYPTION_KEY" "$(gen_secret)"
    echo "[deskwise] Generated fresh local LLM_KEY_ENCRYPTION_KEY in .env"
  fi
  # Never default to Bedrock for local setup.
  case "$AI_MODE" in
    none)
      set_env_kv "$target" "LLM_PROVIDER" "fake"
      ;;
    ollama)
      set_env_kv "$target" "LLM_PROVIDER" "ollama"
      ;;
    gemini)
      set_env_kv "$target" "LLM_PROVIDER" "gemini"
      local existing_key
      existing_key="$(env_value "$target" GEMINI_API_KEY "")"
      if [[ -z "$existing_key" && -t 0 ]]; then
        printf "Enter your Google Gemini API key (stored only in local gitignored .env): "
        read -rs user_key
        echo ""
        if [[ -n "$user_key" ]]; then
          set_env_kv "$target" "GEMINI_API_KEY" "$user_key"
        fi
      fi
      ;;
    openai)
      set_env_kv "$target" "LLM_PROVIDER" "openai"
      local existing_key
      existing_key="$(env_value "$target" OPENAI_API_KEY "")"
      if [[ -z "$existing_key" && -t 0 ]]; then
        printf "Enter your OpenAI API key (stored only in local gitignored .env): "
        read -rs user_key
        echo ""
        if [[ -n "$user_key" ]]; then
          set_env_kv "$target" "OPENAI_API_KEY" "$user_key"
        fi
      fi
      ;;
  esac
}

wait_for_url() {
  local url="$1" label="$2" max_tries="${3:-60}" i=1
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

open_browser() {
  local url="$1"
  if (( NO_BROWSER )) || [[ "${CI:-}" == "true" ]]; then
    return 0
  fi
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 &
  elif command -v open >/dev/null 2>&1; then
    open "$url" >/dev/null 2>&1 &
  fi
}

case "$ACTION" in
  doctor)
    run_doctor
    exit $?
    ;;
  stop)
    docker compose down || true
    echo "[deskwise] Stopped local Deskwise stack."
    exit 0
    ;;
  reset)
    docker compose down -v --remove-orphans || true
    rm -f "$ROOT/.dev-logs/demo-credentials.txt"
    echo "[deskwise] Reset complete (containers stopped and local demo volumes wiped)."
    exit 0
    ;;
esac

run_doctor
ensure_env_file

API_PORT="$(env_value "$ROOT/.env" API_PORT 8000)"
WEB_PORT="$(env_value "$ROOT/.env" WEB_PORT 3000)"

echo "[deskwise] Building and starting Docker containers (api:${API_PORT} + web:${WEB_PORT}) ..."
docker compose up -d --build --wait

echo "[deskwise] Running database migrations & seeding plans ..."
docker compose exec -T api python manage.py migrate --noinput
docker compose exec -T api python manage.py seed_plans

mkdir -p "$ROOT/.dev-logs"
CREDS_FILE="$ROOT/.dev-logs/demo-credentials.txt"
DEMO_PASS=""
if [[ -f "$CREDS_FILE" ]]; then
  DEMO_PASS="$(grep '^Password:' "$CREDS_FILE" | awk '{print $2}' || true)"
fi
DEMO_PASS="${DEMO_PASS:-$(gen_demo_password)}"

echo "[deskwise] Seeding demo personas (Admin, Finance Manager, Employee, Viewer) ..."
docker compose exec -T api python manage.py seed_demo_personas --password "$DEMO_PASS"

cat > "$CREDS_FILE" <<EOF
Password: ${DEMO_PASS}
Admin:    admin@demo.deskwise.local
Finance:  finance@demo.deskwise.local
Employee: employee@demo.deskwise.local
Viewer:   viewer@demo.deskwise.local
EOF
chmod 600 "$CREDS_FILE"

wait_for_url "http://localhost:${API_PORT}/api/health" "Django API" 45
wait_for_url "http://localhost:${WEB_PORT}" "Next.js Web" 45

AI_BANNER="Retrieval-only demo mode (--no-ai). Pass --ai gemini|openai|ollama to enable live LLM generation."
if [[ "$AI_MODE" != "none" ]]; then
  AI_BANNER="AI provider configured: ${AI_MODE} (never defaults to Bedrock)."
fi

cat <<EOF

========================================================================
  Deskwise is LIVE locally!
  ${AI_BANNER}
------------------------------------------------------------------------
  Web App:     http://localhost:${WEB_PORT}
  API Health:  http://localhost:${API_PORT}/api/health

  Demo Personas (Password for all: ${DEMO_PASS})
  +---------------------+-------------------------------+---------------+
  | Role                | Email                         | Clearance     |
  +---------------------+-------------------------------+---------------+
  | Admin               | admin@demo.deskwise.local     | Confidential  |
  | Finance Manager     | finance@demo.deskwise.local   | Internal (Fin)|
  | General Employee    | employee@demo.deskwise.local  | Internal (Eng)|
  | Read-only Viewer    | viewer@demo.deskwise.local    | Standard (HR) |
  +---------------------+-------------------------------+---------------+
  (Credentials saved locally in .dev-logs/demo-credentials.txt — gitignored)

  Verify demo story:  ./scripts/verify_install
  Stop anytime:       ./scripts/start_local.sh --stop
  Wipe & reset:       ./scripts/start_local.sh --reset
========================================================================
EOF

open_browser "http://localhost:${WEB_PORT}"
