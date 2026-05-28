#!/bin/bash
# update-resgov.sh — Build and deploy the ResGov API container safely
# Usage: ./update-resgov.sh
#
# Ensures the container is created in the default bridge network
# so Traefik (running in host network) can reach it.

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "→ Building image..."
docker compose build

echo "→ Creating/updating container in bridge network..."
docker compose down 2>/dev/null || true
docker compose up -d

# Verify Traefik can find the container (it uses label discovery via Docker socket)
# The container must be in bridge network for Traefik host-mode discovery
CONTAINER_ID=$(docker compose ps -q resgov)
NETWORK=$(docker inspect "$CONTAINER_ID" --format '{{range $net,$conf := .NetworkSettings.Networks}}{{$net}}{{end}}')

if [ "$NETWORK" != "bridge" ]; then
    echo "→ Container is in '$NETWORK' network, reconnecting to bridge..."
    docker network disconnect "$NETWORK" "$CONTAINER_ID" 2>/dev/null || true
    docker network connect bridge "$CONTAINER_ID"
fi

echo "→ Verifying health..."
sleep 3
HEALTH=$(docker inspect "$CONTAINER_ID" --format '{{.State.Health.Status}}')
if [ "$HEALTH" = "healthy" ]; then
    echo "✓ ResGov is healthy and accessible via Traefik"
else
    echo "⚠ Health status: $HEALTH (may still be starting)"
fi

echo "→ Current networks:"
docker inspect "$CONTAINER_ID" --format '{{range $net,$conf := .NetworkSettings.Networks}}{{$net}} {{end}}'
