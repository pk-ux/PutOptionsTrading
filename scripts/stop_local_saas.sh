#!/bin/bash
# =============================================================================
# Stop Local SaaS Testing
# =============================================================================

set -e

echo "Stopping local SaaS stack..."

# Stop Streamlit
pkill -f "streamlit run app.py" 2>/dev/null || true

# Stop FastAPI
pkill -f "uvicorn main:app" 2>/dev/null || true

# Stop PostgreSQL (optional - keeps data)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

read -p "Stop PostgreSQL container? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    docker-compose down
    echo "PostgreSQL stopped."
else
    echo "PostgreSQL still running. Stop with: docker-compose down"
fi

echo "Done!"
