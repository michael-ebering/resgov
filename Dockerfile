FROM python:3.12-slim

WORKDIR /app

# Install runtime deps (no build tools needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Verify Python sqlite3 module works
RUN python3 -c "import sqlite3; c=sqlite3.connect('/tmp/_test.db'); c.execute('SELECT 1'); c.close(); import os; os.unlink('/tmp/_test.db'); print('SQLite OK')"

# Install Python dependencies
RUN pip install --no-cache-dir \
    fastapi==0.136.3 \
    uvicorn==0.49.0 \
    pydantic==2.13.4 \
    apscheduler==3.11.2 \
    httpx==0.28.1

COPY src/ ./src/
COPY dash/ ./dash/
COPY scripts/backup.sh /app/scripts/backup.sh
COPY .rgf /app/.rgf

RUN mkdir -p /data /data/backups \
    && chmod 777 /data \
    && chmod +x /app/scripts/backup.sh

ENV RESGOV_DB_PATH=/data/resgov.db
ENV RESGOV_BACKUP_DIR=/data/backups
ENV RESGOV_BACKUP_RETENTION=7

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["python", "-m", "uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8080"]