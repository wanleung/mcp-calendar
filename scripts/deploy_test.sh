#!/bin/bash
set -e

COMPOSE_FILE="docker-compose.test.yml"
BASE_URL="${BASE_URL:-http://localhost:8000}"
MAX_WAIT=60
INTERVAL=2

cleanup() {
    echo "🧹 Tearing down test stack..."
    docker compose -f "$COMPOSE_FILE" down -v --remove-orphans 2>/dev/null || true
}

trap cleanup EXIT

echo "🚀 Starting Calendar MCP Service test stack..."
docker compose -f "$COMPOSE_FILE" up -d --build

echo "⏳ Waiting for service to become healthy..."
elapsed=0
while [ $elapsed -lt $MAX_WAIT ]; do
    if curl -sf "$BASE_URL/health" > /dev/null 2>&1; then
        echo "✅ Service is healthy after ${elapsed}s"
        break
    fi
    sleep $INTERVAL
    elapsed=$((elapsed + INTERVAL))
done

if [ $elapsed -ge $MAX_WAIT ]; then
    echo "❌ Service failed to become healthy within ${MAX_WAIT}s"
    docker compose -f "$COMPOSE_FILE" logs
    exit 1
fi

echo "🧪 Running deployment smoke tests..."
if pytest tests/test_deployment.py -v --tb=short; then
    echo "✅ All smoke tests passed!"
    exit 0
else
    echo "❌ Smoke tests failed!"
    exit 1
fi

# Deployment Test Plan: Calendar MCP Service — Apple Calendar Feature Parity

## Services Tested
| Service | Port | Health Check |
|---------|------|--------------|
| calendar-mcp | 8000 | GET /health |

## Smoke Tests
| Test | Endpoint | Expected |
|------|----------|----------|
| Health check | GET /health | 200 OK, `{"status": "healthy", "version": "1.0.0"}` |
| Health content type | GET /health | 200 OK, `application/json` content type |
| MCP initialize | POST /initialize | 200 OK, protocol version 2024-11-05 |
| MCP initialize capabilities | POST /initialize | 200 OK, tools.list=true |
| MCP tools list | POST /messages | 200 OK, list of tools returned |
| MCP tools contain calendar tools | POST /messages | 200 OK, list_calendars/get_events/create_event present |
| Unknown tool returns error | POST /messages | 200 OK, isError=true |
| Unknown GET route | GET /api/v1/nonexistent | 404 Not Found |
| Unknown POST route | POST /api/v1/nonexistent | 404 Not Found |

## How to Run Locally
chmod +x scripts/deploy_test.sh
./scripts/deploy_test.sh

## CI Integration
These tests run in the `deploy-test` job in `.github/workflows/run-tests.yml`.