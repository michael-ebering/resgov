FROM python:3.12-slim

WORKDIR /app

# Compile SQLite 3.50.2 from source (fixes CVE-2025-3277, CVE-2025-6965, CVE-2025-7709, CVE-2025-7458, CVE-2025-29087, CVE-2025-29088)
# Need build-essential equivalent: gcc, make, tcl, libc headers
RUN apt-get update && apt-get install -y --no-install-recommends gcc make wget tcl libc6-dev \
    && wget -q https://www.sqlite.org/2025/sqlite-autoconf-3500200.tar.gz \
    && tar xzf sqlite-autoconf-3500200.tar.gz \
    && cd sqlite-autoconf-3500200 \
    && ./configure --prefix=/usr/local --enable-fts5 \
    && make -j$(nproc) \
    && make install \
    && ldconfig \
    && cd .. \
    && rm -rf sqlite-autoconf-3500200* \
    && rm -rf /var/lib/apt/lists/*

# Verify SQLite version
RUN python3 -c "import sqlite3; assert sqlite3.sqlite_version_info >= (3, 50, 2), f'SQLite {sqlite3.sqlite_version} too old'; print(f'SQLite {sqlite3.sqlite_version} OK')"

# Install Python dependencies with version pinning
RUN pip install --no-cache-dir \
    fastapi==0.136.3 \
    uvicorn==0.49.0 \
    pydantic==2.13.4 \
    apscheduler==3.11.2 \
    httpx==0.28.1

# Install sqlite3 CLI for manual backup
RUN apt-get update && apt-get install -y --no-install-recommends sqlite3 && rm -rf /var/lib/apt/lists/*

COPY src/ ./src/
COPY dash/ ./dash/
COPY scripts/backup.sh /app/scripts/backup.sh
COPY .rgf /app/.rgf

RUN mkdir -p /data /data/backups
RUN chmod +x /app/scripts/backup.sh

# Create non-root user
RUN groupadd -r resgov && useradd -r -g resgov -d /app -s /sbin/nologin resgov
RUN chown -R resgov:resgov /app

ENV RESGOV_DB_PATH=/data/resgov.db
ENV RESGOV_BACKUP_DIR=/data/backups
ENV RESGOV_BACKUP_RETENTION=7

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# Run as non-root
USER resgov
CMD ["python", "-m", "uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8080"]
