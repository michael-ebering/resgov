#!/usr/bin/env bash
# ResGov (RGF) — One-Command Installer
# Tested on: Ubuntu 22.04/24.04, Debian 12
# Usage: curl -fsSL https://raw.githubusercontent.com/michael-ebering/resgov/main/install.sh | bash
# Or: wget -qO- https://raw.githubusercontent.com/michael-ebering/resgov/main/install.sh | bash

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

# --- Checks ---

command -v docker >/dev/null 2>&1 || {
  err "Docker not found. Install Docker first:\n  curl -fsSL https://get.docker.com | sudo sh\n  sudo usermod -aG docker \$USER"
}

docker compose version >/dev/null 2>&1 || {
  err "Docker Compose not found. Install plugin:\n  sudo apt-get install -y docker-compose-plugin"
}

# --- Directory ---

INSTALL_DIR="${RESGOV_INSTALL_DIR:-/opt/resgov}"
if [ -d "$INSTALL_DIR" ]; then
  warn "Directory $INSTALL_DIR exists. Updating..."
  cd "$INSTALL_DIR"
  git pull --rebase origin main >/dev/null 2>&1 || warn "Git pull failed, using local files"
else
  log "Cloning ResGov to $INSTALL_DIR..."
  sudo mkdir -p "$INSTALL_DIR"
  sudo chown "$(whoami):$(whoami)" "$INSTALL_DIR"
  git clone https://github.com/michael-ebering/resgov.git "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi

# --- Config ---

if [ ! -f .env ]; then
  ADMIN_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  cat > .env <<EOF
# ResGov Environment Configuration
# Generated on $(date -u +%Y-%m-%dT%H:%M:%SZ)

# Authentication (REQUIRED)
RESGOV_ADMIN_TOKEN=${ADMIN_TOKEN}
RESGOV_API_KEYS=

# Server
RESGOV_HOST=0.0.0.0
RESGOV_PORT=8080

# Dashboard (leave DASH_PASS empty to disable auth)
RESGOV_DASH_USER=admin
RESGOV_DASH_PASS=

# Backups
RESGOV_BACKUP_DIR=/data/backups
RESGOV_BACKUP_RETENTION=7

# Optional: Email capture for lead collection
# RESGOV_LEAD_EMAIL_SMTP_HOST=
# RESGOV_LEAD_EMAIL_SMTP_PORT=587
# RESGOV_LEAD_EMAIL_SMTP_USER=
# RESGOV_LEAD_EMAIL_SMTP_PASS=
# RESGOV_LEAD_EMAIL_FROM=
EOF
  log "Created .env with auto-generated admin token"
  echo ""
  echo -e "${GREEN}Your Admin Token (save this!):${NC}"
  echo -e "${YELLOW}${ADMIN_TOKEN}${NC}"
  echo ""
  echo "Add it to your password manager. You need it for:"
  echo "  - Generating API keys"
  echo "  - Accessing admin endpoints"
  echo "  - Price cache refresh"
else
  log ".env already exists, keeping current config"
  ADMIN_TOKEN="$(grep RESGOV_ADMIN_TOKEN .env | head -1 | cut -d= -f2)"
fi

# --- Start ---

log "Building and starting ResGov..."
docker compose build --no-cache 2>&1 | tail -3
docker compose up -d

# --- Wait for health ---

log "Waiting for ResGov to start..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8080/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

# --- Verify ---

HEALTH="$(curl -sf http://localhost:8080/health 2>/dev/null || echo '{"status":"error}")"
STATUS="$(echo "$HEALTH" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("status","?"))' 2>/dev/null || echo "?")"
VERSION="$(echo "$HEALTH" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("version","?"))' 2>/dev/null || echo "?")"

if [ "$STATUS" = "ok" ]; then
  log "ResGov v${VERSION} is running and healthy!"
else
  warn "Container started but health check failed. Check logs:"
  echo "  docker compose logs resgov --tail 50"
fi

# --- Generate initial API key ---

echo ""
read -rp "Generate an API key now? [y/N] " REPLY
if [[ "$REPLY" =~ ^[Yy] ]]; then
  read -rp "Owner/Project name (default: admin): " OWNER
  OWNER="${OWNER:-admin}"

  RESULT="$(curl -sf -X POST http://localhost:8080/api/v1/admin/generate-key \
    -H "X-Admin-Token: ${ADMIN_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"owner\": \"${OWNER}\"}" 2>/dev/null || echo '{"error":"failed"}')"

  API_KEY="$(echo "$RESULT" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("api_key",""))' 2>/dev/null || echo "")"

  if [ -n "$API_KEY" ]; then
    log "API Key generated:"
    echo -e "${GREEN}${API_KEY}${NC}"
    echo ""
    echo "Use this key in your requests:"
    echo "  curl -H \"X-API-Key: ${API_KEY}\" http://localhost:8080/api/v1/agents"
  else
    warn "API key failed to generate. Generate manually later:"
    echo "  curl -X POST http://localhost:8080/api/v1/admin/generate-key \\"
    echo "    -H \"X-Admin-Token: ${ADMIN_TOKEN}\" \\"
    echo "    -H \"Content-Type: application/json\" \\"
    echo "    -d '{\"owner\": \"${OWNER}\"}'"
  fi
fi

echo ""
log "Installation complete!"
echo ""
echo "Next steps:"
echo "  Dashboard:  http://localhost:8080/dash"
echo "  API Docs:   http://localhost:8080/docs"
echo "  Health:     http://localhost:8080/health"
echo ""
echo "For HTTPS/Traefik setup, see: https://github.com/michael-ebering/resgov/blob/main/DEPLOYMENT.md"
