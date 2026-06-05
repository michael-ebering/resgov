#!/bin/sh
# ResGov Entrypoint – fix volume permissions, then drop to non-root
set -e

# Fix ownership of /data volume (runs as root, then drops)
chown -R resgov:resgov /data 2>/dev/null || true

# Drop to non-root user and exec
exec su -p resgov -c 'cd /app && exec python -m uvicorn src.api:app --host 0.0.0.0 --port 8080'
