#!/bin/bash
# ResGov WAL Backup Script
# Backs up the SQLite database using .backup command (safe for WAL mode)
# Run via cron: 0 3 * * * /opt/resgov/scripts/backup.sh

set -euo pipefail

DB_PATH="${RESGOV_DB_PATH:-/data/resgov.db}"
BACKUP_DIR="${RESGOV_BACKUP_DIR:-/data/backups}"
RETENTION_DAYS="${RESGOV_BACKUP_RETENTION:-7}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/resgov_${TIMESTAMP}.db"

mkdir -p "$BACKUP_DIR"

echo "[$(date)] Starting ResGov backup..."
echo "  Source: $DB_PATH"
echo "  Target: $BACKUP_FILE"

# Use .backup for atomic copy (works with WAL mode)
sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"

# Verify backup
if [ -f "$BACKUP_FILE" ]; then
    ORIG_SIZE=$(stat -c%s "$DB_PATH" 2>/dev/null || echo "0")
    BACKUP_SIZE=$(stat -c%s "$BACKUP_FILE" 2>/dev/null || echo "0")
    echo "  Original: ${ORIG_SIZE} bytes | Backup: ${BACKUP_SIZE} bytes"
    echo "[$(date)] Backup successful: $BACKUP_FILE"
else
    echo "[$(date)] ERROR: Backup file not created!"
    exit 1
fi

# Delete old backups
DELETED=$(find "$BACKUP_DIR" -name "resgov_*.db" -mtime "+${RETENTION_DAYS}" | wc -l)
find "$BACKUP_DIR" -name "resgov_*.db" -mtime "+${RETENTION_DAYS}" -delete
echo "[$(date)] Cleaned up $DELETED old backup(s) (> ${RETENTION_DAYS} days)"
