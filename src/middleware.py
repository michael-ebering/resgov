"""
ResGov — Middleware & Utilities
Rate limiting, connection management, CORS, logging.
"""
import time
import logging
import sqlite3
import threading
import os
from collections import defaultdict
from contextlib import contextmanager
from typing import Optional

from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

# --- Logging Setup ---

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("resgov")


# --- Connection Management ---

# Thread-local storage for database connections
_local = threading.local()


def get_db_path() -> str:
    """Get the database path from environment."""
    return os.environ.get("RESGOV_DB_PATH", "/data/resgov.db")


def get_db() -> sqlite3.Connection:
    """Get a thread-local database connection."""
    if not hasattr(_local, "connection") or _local.connection is None:
        db_path = get_db_path()
        _local.connection = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
        _local.connection.execute("PRAGMA journal_mode=WAL")
        _local.connection.execute("PRAGMA foreign_keys=ON")
        _local.connection.row_factory = sqlite3.Row
    return _local.connection


@contextmanager
def get_transaction():
    """
    Context manager for write operations with BEGIN IMMEDIATE.
    Ensures row-level locking for concurrent writes.
    """
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise


def close_db():
    """Close the thread-local database connection."""
    if hasattr(_local, "connection") and _local.connection:
        _local.connection.close()
        _local.connection = None


# Pool API for compatibility (simplified)
class ConnectionPool:
    def __init__(self, db_path: str):
        os.environ["RESGOV_DB_PATH"] = db_path

    def close_all(self):
        close_db()


# --- Rate Limiting ---

class RateLimiter:
    """
    In-memory sliding window rate limiter.
    For production, use Redis. For MVP, this is sufficient.
    """

    def __init__(self, requests_per_minute: int = 60, burst: int = 10):
        self.rpm = requests_per_minute
        self.burst = burst
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> tuple[bool, dict]:
        """
        Check if a request is allowed.
        Returns (allowed, info_dict).
        """
        now = time.time()
        window = 60.0  # 1 minute window

        with self._lock:
            # Clean old entries
            self._requests[key] = [
                t for t in self._requests[key] if now - t < window
            ]

            current_count = len(self._requests[key])

            if current_count >= self.rpm:
                retry_after = self._requests[key][0] + window - now
                return False, {
                    "limit": self.rpm,
                    "remaining": 0,
                    "retry_after": round(retry_after, 1),
                }

            if current_count >= self.burst:
                # Allow but warn
                pass

            self._requests[key].append(now)
            remaining = self.rpm - current_count - 1

            return True, {
                "limit": self.rpm,
                "remaining": remaining,
                "reset": round(now + window, 0),
            }


# Global rate limiter
_rate_limiter = RateLimiter(requests_per_minute=60, burst=10)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply rate limiting to all API requests."""

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks
        if request.url.path in ("/health", "/docs", "/openapi.json"):
            return await call_next(request)

        # Use API key or IP as rate limit key
        api_key = request.headers.get("X-API-Key", "")
        client_ip = request.client.host if request.client else "unknown"
        key = api_key or client_ip

        allowed, info = _rate_limiter.is_allowed(key)

        if not allowed:
            logger.warning(f"Rate limit exceeded: {key}")
            return Response(
                content=f'{{"error":"rate_limit_exceeded","retry_after":{info["retry_after"]}}}',
                status_code=429,
                media_type="application/json",
                headers={
                    "X-RateLimit-Limit": str(info["limit"]),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": str(info["retry_after"]),
                },
            )

        response = await call_next(request)

        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(info["limit"])
        response.headers["X-RateLimit-Remaining"] = str(info["remaining"])

        return response


# --- Request Logging Middleware ---

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log all requests with timing."""

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = round((time.time() - start) * 1000, 2)

        logger.info(
            f"{request.method} {request.url.path} "
            f"→ {response.status_code} ({duration}ms) "
            f"client={request.client.host if request.client else '?'}"
        )

        response.headers["X-Response-Time"] = f"{duration}ms"
        return response


# --- CORS Setup ---

def setup_cors(app):
    """Configure CORS for the app."""
    origins = [
        "https://resgov.silentops.cloud",
        "https://api.resgov.silentops.cloud",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "X-Admin-Token", "X-ResGov-Agent-ID"],
        expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-Response-Time"],
    )
