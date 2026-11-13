#!/usr/bin/env bash
# ==============================================================================
# Deskwise — Unified Stop Script
#
# Stops all Deskwise services: frontend, backend, and database containers
# (plus native host dev servers if running).
#
# Usage:
#   ./stop.sh            Stop Docker containers AND native backend/frontend
#   ./stop.sh --native   Stop only native host backend/frontend processes
# ==============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT/.dev-logs"
NATIVE_ONLY=0

if [[ "${1:-}" == "--native" ]]; then
  NATIVE_ONLY=1
fi

kill_pidfile() {
  local pidfile="$1"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid="$(cat "$pidfile" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
    fi
    rm -f "$pidfile"
  fi
}

echo "[deskwise] Stopping native backend & frontend processes ..."
kill_pidfile "$LOG_DIR/backend.pid"
kill_pidfile "$LOG_DIR/frontend.pid"
kill_pidfile "$LOG_DIR/ollama-bridge.pid"

pkill -f "$ROOT/backend" >/dev/null 2>&1 || true
pkill -f "$ROOT/frontend" >/dev/null 2>&1 || true

if [[ "$NATIVE_ONLY" == "0" ]] && command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    echo "[deskwise] Stopping Docker Compose containers (api, web, db, redis) ..."
    (cd "$ROOT" && docker compose --profile pg --profile redis down --remove-orphans) || true
  fi
fi

sleep 1
echo "[deskwise] All servers stopped."
