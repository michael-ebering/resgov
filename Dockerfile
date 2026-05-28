FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn pydantic apscheduler httpx

# Install sqlite3 CLI for backup scripts
RUN apt-get update && apt-get install -y --no-install-recommends sqlite3 cron && rm -rf /var/lib/apt/lists/*

COPY src/ ./src/
COPY dash/ ./dash/
COPY scripts/backup.sh /app/scripts/backup.sh

RUN mkdir -p /data /data/backups
RUN chmod +x /app/scripts/backup.sh

ENV RESGOV_DB_PATH=/data/resgov.db
ENV RESGOV_BACKUP_DIR=/data/backups
ENV RESGOV_BACKUP_RETENTION=7

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# Start cron + uvicorn
CMD ["sh", "-c", "echo '0 3 * * * /app/scripts/backup.sh >> /data/backup.log 2>&1' | crontab - && cron && python -m uvicorn src.api:app --host 0.0.0.0 --port 8080"]
