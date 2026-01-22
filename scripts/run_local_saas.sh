#!/bin/bash
# =============================================================================
# Local SaaS Testing Script
# =============================================================================
# This script starts the full SaaS stack locally for testing:
# - PostgreSQL database (via Docker)
# - FastAPI backend (port 8000)
# - Streamlit frontend (port 8501)
#
# Usage: ./scripts/run_local_saas.sh
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo -e "${GREEN}=== Put Options Screener - Local SaaS Testing ===${NC}"
echo ""

# Check for Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker is not installed. Please install Docker first.${NC}"
    echo "Download from: https://www.docker.com/products/docker-desktop"
    exit 1
fi

# Check if Docker is running
if ! docker info &> /dev/null; then
    echo -e "${RED}Docker is not running. Please start Docker Desktop.${NC}"
    exit 1
fi

# Step 1: Start PostgreSQL
echo -e "${YELLOW}[1/4] Starting PostgreSQL database...${NC}"
docker-compose up -d postgres
sleep 3

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL to be ready..."
for i in {1..30}; do
    if docker-compose exec -T postgres pg_isready -U postgres &> /dev/null; then
        echo -e "${GREEN}PostgreSQL is ready!${NC}"
        break
    fi
    sleep 1
done

# Step 2: Install backend dependencies
echo -e "${YELLOW}[2/4] Installing backend dependencies...${NC}"
cd "$PROJECT_DIR/backend"
if [ -d "../.venv" ]; then
    source "../.venv/bin/activate"
fi
pip install -q -r requirements.txt

# Step 3: Start FastAPI backend
echo -e "${YELLOW}[3/4] Starting FastAPI backend on port 8000...${NC}"
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/options_screener"
export MASSIVE_API_KEY="${MASSIVE_API_KEY:-}"
# No Clerk keys = dev mode with mock auth

# Kill any existing backend
pkill -f "uvicorn main:app" 2>/dev/null || true
sleep 1

# Start backend in background
cd "$PROJECT_DIR/backend"
uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
sleep 3

# Verify backend is running
if curl -s http://localhost:8000/health > /dev/null; then
    echo -e "${GREEN}Backend is running!${NC}"
else
    echo -e "${RED}Backend failed to start. Check logs above.${NC}"
    exit 1
fi

# Step 4: Start Streamlit frontend
echo -e "${YELLOW}[4/4] Starting Streamlit frontend on port 8501...${NC}"
cd "$PROJECT_DIR"

# Kill any existing frontend
pkill -f "streamlit run app.py" 2>/dev/null || true
sleep 1

# Set API_URL to point to local backend
export API_URL="http://localhost:8000"

# Start frontend in background
streamlit run app.py --server.port 8501 --server.address 0.0.0.0 &
FRONTEND_PID=$!
sleep 3

echo ""
echo -e "${GREEN}=== Local SaaS Stack is Running ===${NC}"
echo ""
echo "  Frontend:  http://localhost:8501"
echo "  Backend:   http://localhost:8000"
echo "  API Docs:  http://localhost:8000/docs"
echo "  Database:  postgresql://postgres:postgres@localhost:5432/options_screener"
echo ""
echo -e "${YELLOW}Notes:${NC}"
echo "  - Auth is in DEV MODE (no Clerk required)"
echo "  - Mock user: dev@example.com"
echo "  - Settings are persisted to PostgreSQL"
echo ""
echo "To stop: ./scripts/stop_local_saas.sh"
echo ""

# Keep script running and show logs
wait
