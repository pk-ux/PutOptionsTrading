#!/bin/bash
# Restart the local dev servers (FastAPI backend + Vite frontend).
# - Kills any existing uvicorn/vite instances (and frees the ports)
# - Starts both in the background, logging to .dev-logs/
# - Verifies the backend health endpoint
#
# Usage:
#   .cursor/skills/restart-dev-servers/scripts/restart-dev.sh           # restart both
#   .cursor/skills/restart-dev-servers/scripts/restart-dev.sh stop      # just kill
#   BACKEND_PORT=8001 FRONTEND_PORT=5174 ...restart-dev.sh              # override ports

set -u

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

# Project root = four levels up from this script (.cursor/skills/<skill>/scripts)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$PROJECT_DIR"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
LOG_DIR="$PROJECT_DIR/.dev-logs"
mkdir -p "$LOG_DIR"

kill_existing() {
  echo -e "${YELLOW}Stopping existing dev servers...${NC}"
  pkill -f "uvicorn app.main:app" 2>/dev/null || true
  pkill -f "vite" 2>/dev/null || true
  # Free the ports as a backup (in case of orphaned processes)
  for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
    pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
    [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
  done
  sleep 1
}

if [ "${1:-}" = "stop" ]; then
  kill_existing
  echo -e "${GREEN}Dev servers stopped.${NC}"
  exit 0
fi

kill_existing

# Activate a virtualenv (prefer .venv, which has the full app deps; fall back to backend/venv)
if [ -d "$PROJECT_DIR/.venv" ]; then
  source "$PROJECT_DIR/.venv/bin/activate"
elif [ -d "$PROJECT_DIR/backend/venv" ]; then
  source "$PROJECT_DIR/backend/venv/bin/activate"
else
  echo -e "${RED}No virtualenv found (.venv or backend/venv).${NC}"
  exit 1
fi

# Load backend/.env so DATABASE_URL, API keys, etc. are available
if [ -f "$PROJECT_DIR/backend/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/backend/.env"
  set +a
fi
export DATABASE_URL="${DATABASE_URL:-sqlite:///./local_test.db}"
export CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:3000,http://localhost:5173}"

# --- Backend ---
echo -e "${YELLOW}Starting backend on :$BACKEND_PORT...${NC}"
cd "$PROJECT_DIR/backend"
nohup uvicorn app.main:app --reload --host 0.0.0.0 --port "$BACKEND_PORT" \
  > "$LOG_DIR/backend.log" 2>&1 &
echo "Backend PID: $!"

# Wait for health (up to ~20s)
ok=0
for _ in $(seq 1 20); do
  if curl -s "http://localhost:$BACKEND_PORT/health" > /dev/null 2>&1; then ok=1; break; fi
  sleep 1
done
if [ "$ok" = "1" ]; then
  echo -e "${GREEN}Backend healthy at http://localhost:$BACKEND_PORT${NC}"
else
  echo -e "${RED}Backend did not pass health check. See $LOG_DIR/backend.log${NC}"
fi

# --- Frontend ---
cd "$PROJECT_DIR/frontend"
if [ ! -d "node_modules" ]; then
  echo -e "${YELLOW}Installing frontend dependencies...${NC}"
  npm install
fi
echo -e "${YELLOW}Starting frontend on :$FRONTEND_PORT...${NC}"
nohup npm run dev -- --port "$FRONTEND_PORT" > "$LOG_DIR/frontend.log" 2>&1 &
echo "Frontend PID: $!"

echo ""
echo -e "${GREEN}=== Dev servers running ===${NC}"
echo "  Frontend:  http://localhost:$FRONTEND_PORT"
echo "  Backend:   http://localhost:$BACKEND_PORT"
echo "  API Docs:  http://localhost:$BACKEND_PORT/docs"
echo "  Logs:      $LOG_DIR/backend.log , $LOG_DIR/frontend.log"
