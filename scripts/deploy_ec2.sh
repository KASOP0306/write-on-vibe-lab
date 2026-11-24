#!/usr/bin/env bash
set -euo pipefail

echo "==> [1/4] Checking .env file..."
if [ ! -f ".env" ]; then
  echo "ERROR: .env file not found. Copy .env.example to .env and configure POSTGRES_PASSWORD and AWS_REGION first."
  exit 1
fi
chmod 600 .env

echo "==> [2/4] Pulling latest main branch..."
git pull --ff-only origin main

echo "==> [3/4] Building & starting Docker Compose stack (preserving pgdata volume)..."
docker compose up -d --build

echo "==> [4/4] Waiting for backend healthcheck via Nginx (/api/health)..."
for i in $(seq 1 20); do
  if curl -fsS http://localhost/api/health >/dev/null 2>&1; then
    echo "SUCCESS: Service is healthy!"
    curl -fsS http://localhost/api/health
    echo ""
    exit 0
  fi
  sleep 2
done

echo "ERROR: Health check timed out. Inspect logs with: docker compose logs -f backend frontend db"
exit 1
