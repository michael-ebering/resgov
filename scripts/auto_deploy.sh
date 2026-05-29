#!/bin/bash
# ResGov Auto-Deploy Script
# Prüft alle 5 Minuten auf neue Commits auf origin/main
# und deployed automatisch wenn es Änderungen gibt.

set -euo pipefail

REPO_DIR="/root/documents/resgov"
LOG_FILE="/var/log/resgov-deploy.log"
LOCK_FILE="/tmp/resgov-deploy.lock"

# Prevents overlapping runs
if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        echo "$(date -Iseconds) [SKIP] Another deploy is running (PID $PID)" >> "$LOG_FILE"
        exit 0
    fi
fi
echo $$ > "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

cd "$REPO_DIR"

# Fetch latest from origin
git fetch origin main 2>/dev/null

LOCAL=$(git rev-parse HEAD 2>/dev/null || echo "none")
REMOTE=$(git rev-parse origin/main 2>/dev/null || echo "none")

if [ "$LOCAL" = "$REMOTE" ]; then
    echo "$(date -Iseconds) [OK] Already up to date ($LOCAL)" >> "$LOG_FILE"
    exit 0
fi

echo "$(date -Iseconds) [DEPLOY] New commit detected: $LOCAL → $REMOTE" >> "$LOG_FILE"

# Pull latest code
git pull --rebase origin main >> "$LOG_FILE" 2>&1

# Rebuild and restart container
docker compose build --no-cache resgov >> "$LOG_FILE" 2>&1
docker compose up -d resgov >> "$LOG_FILE" 2>&1

# Wait and health check
sleep 5
HEALTH=$(curl -sf http://localhost:8080/health 2>/dev/null || echo "FAILED")

if echo "$HEALTH" | grep -q '"status":"ok"'; then
    echo "$(date -Iseconds) [SUCCESS] Deployed $REMOTE successfully. Health: $HEALTH" >> "$LOG_FILE"
else
    echo "$(date -Iseconds) [ERROR] Deploy failed! Health: $HEALTH" >> "$LOG_FILE"
    exit 1
fi
