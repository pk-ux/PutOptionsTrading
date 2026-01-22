#!/bin/bash
# =============================================================================
# Local SaaS Testing Script (SQLite version - no Docker required)
# =============================================================================
# This script starts the full SaaS stack locally for testing:
# - SQLite database (file-based, no setup needed)
# - FastAPI backend (port 8000)
# - Streamlit frontend (port 8501)
#
# Usage: ./scripts/run_local_saas_sqlite.sh
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo -e "${GREEN}=== Put Options Screener - Local SaaS Testing (SQLite) ===${NC}"
echo ""

# Activate virtual environment if exists
if [ -d ".venv" ]; then
    source ".venv/bin/activate"
    echo -e "${GREEN}Virtual environment activated${NC}"
fi

# Step 1: Install backend dependencies
echo -e "${YELLOW}[1/3] Installing backend dependencies...${NC}"
cd "$PROJECT_DIR/backend"
pip install -q -r requirements.txt

# Step 2: Start FastAPI backend
echo -e "${YELLOW}[2/3] Starting FastAPI backend on port 8000...${NC}"

# Use SQLite for local testing (stored in backend/local_test.db)
export DATABASE_URL="sqlite:///$PROJECT_DIR/backend/local_test.db"
export MASSIVE_API_KEY="${MASSIVE_API_KEY:-$(grep MASSIVE_API_KEY $PROJECT_DIR/.env 2>/dev/null | cut -d= -f2)}"
# No Clerk keys = dev mode with mock auth

# Kill any existing backend
pkill -f "uvicorn main:app" 2>/dev/null || true
sleep 1

# Start backend in background
cd "$PROJECT_DIR/backend"
uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"
sleep 3

# Verify backend is running
if curl -s http://localhost:8000/health > /dev/null; then
    echo -e "${GREEN}Backend is running!${NC}"
else
    echo -e "${RED}Backend failed to start. Check logs above.${NC}"
    exit 1
fi

# Step 3: Start Streamlit frontend
echo -e "${YELLOW}[3/3] Starting Streamlit frontend on port 8501...${NC}"
cd "$PROJECT_DIR"

# Kill any existing frontend
pkill -f "streamlit run app.py" 2>/dev/null || true
sleep 1

# Set API_URL to point to local backend (enables SaaS mode)
export API_URL="http://localhost:8000"

# Start frontend in background
streamlit run app.py --server.port 8501 --server.address 0.0.0.0 &
FRONTEND_PID=$!
echo "Frontend PID: $FRONTEND_PID"
sleep 3

echo ""
echo -e "${GREEN}=== Local SaaS Stack is Running ===${NC}"
echo ""
echo "  Frontend:    http://localhost:8501"
echo "  Backend:     http://localhost:8000"
echo "  API Docs:    http://localhost:8000/docs"
echo "  Test Screen: http://localhost:8000/api/v1/test-screen?symbol=AAPL"
echo "  Database:    $PROJECT_DIR/backend/local_test.db"
echo ""
echo -e "${YELLOW}Notes:${NC}"
echo "  - Auth is in DEV MODE (no Clerk required)"
echo "  - Mock user: dev@example.com"
echo "  - Settings are persisted to SQLite"
echo ""
echo "Press Ctrl+C to stop both services"
echo ""

# Trap Ctrl+C to clean up
trap "echo 'Stopping...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" SIGINT SIGTERM

# Keep script running
wait
