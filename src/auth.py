"""
ResGov — Authentication & Authorization
Database-backed API key management with admin token support.
"""
import os
import secrets
import hashlib
import sqlite3
import sqlite3
import threading
from typing import Optional
from fastapi import Header, HTTPException, Request

# Use the shared thread-local _local from middleware (single source of truth)
from .middleware import _local


def _get_admin_token() -> str:
    """Read admin token from env on every call (avoids stale module-level cache in tests)."""
    return os.environ.get("RESGOV_ADMIN_TOKEN", os.environ.get("RESGOV_ADMIN_KEY", ""))


ADMIN_TOKEN = _get_admin_token()


def _get_db() -> sqlite3.Connection:
    """Get thread-local DB connection (delegates to middleware)."""
    if not hasattr(_local, "connection") or _local.connection is None:
        from .middleware import get_db
        _local.connection = get_db()
    return _local.connection


def _hash_key(key: str) -> str:
    """Hash an API key for storage (SHA-256). Never store plaintext."""
    return hashlib.sha256(key.encode()).hexdigest()


def init_api_keys_table():
    """Create the api_keys table if it doesn't exist. Called during app startup."""
    db = _get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_hash TEXT NOT NULL UNIQUE,
            owner TEXT NOT NULL DEFAULT 'anonymous',
            org_id TEXT NOT NULL DEFAULT 'default',
            name TEXT DEFAULT '',
            provider TEXT DEFAULT 'all',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at TEXT,
            scopes TEXT DEFAULT 'read,write'
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)
    """)
    # Migration: add provider column if not exists (SQLite >= 3.2.0)
    try:
        db.execute("ALTER TABLE api_keys ADD COLUMN provider TEXT DEFAULT 'all'")
    except Exception:
        pass  # Column already exists
    db.commit()

    # Migrate legacy ENV keys into DB
    env_keys = os.environ.get("RESGOV_API_KEYS", "")
    if env_keys:
        for pair in env_keys.split(","):
            pair = pair.strip()
            if not pair:
                continue
            if ":" in pair:
                key, owner = pair.split(":", 1)
                key, owner = key.strip(), owner.strip()
            else:
                key, owner = pair, "anonymous"
            try:
                db.execute(
                    "INSERT OR IGNORE INTO api_keys (key_hash, owner, org_id) VALUES (?, ?, 'default')",
                    (_hash_key(key), owner),
                )
            except Exception:
                pass
        db.commit()


def verify_api_key(api_key: Optional[str] = None, provider: str = "all") -> dict:
    """
    Verify an API key. Returns dict with owner, org_id, scopes.

    Args:
        api_key: The API key from X-API-Key header
        provider: The provider being accessed (e.g., "openai", "anthropic").
                  Keys with provider="all" or matching provider are accepted.
    """
    # Dev mode: no admin token, no keys in DB → allow all
    if not _get_admin_token() and not _has_any_keys():
        return {"owner": "dev", "org_id": "default", "scopes": "read,write"}

    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")

    key_hash = _hash_key(api_key)
    db = _get_db()
    row = db.execute(
        "SELECT * FROM api_keys WHERE key_hash = ? AND is_active = 1",
        (key_hash,),
    ).fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Check provider scoping
    key_provider = row["provider"] or "all"
    if key_provider != "all" and key_provider != provider:
        raise HTTPException(
            status_code=403,
            detail=f"API key not authorized for provider '{provider}'. Key is scoped to '{key_provider}'."
        )

    # Check expiry
    if row["expires_at"]:
        from datetime import datetime, timezone
        try:
            expiry = datetime.fromisoformat(row["expires_at"])
            if datetime.now(timezone.utc) > expiry:
                raise HTTPException(status_code=401, detail="API key expired")
        except (ValueError, TypeError):
            pass

    return {
        "owner": row["owner"],
        "org_id": row["org_id"],
        "scopes": row["scopes"] or "read,write",
        "provider": key_provider,
    }


def _has_any_keys() -> bool:
    """Check if there are any API keys in the database."""
    try:
        db = _get_db()
        row = db.execute("SELECT COUNT(*) as cnt FROM api_keys WHERE is_active = 1").fetchone()
        return row["cnt"] > 0
    except Exception:
        return False


def verify_admin_token(admin_token: Optional[str] = None) -> None:
    """
    Verify admin token for privileged operations.
    Raises 403 if invalid.
    """
    effective_token = _get_admin_token()
    if not effective_token:
        return  # Dev mode

    if not admin_token:
        raise HTTPException(status_code=403, detail="Missing X-Admin-Token header")

    if not secrets.compare_digest(admin_token, effective_token):
        raise HTTPException(status_code=403, detail="Invalid admin token")


def generate_api_key() -> str:
    """Generate a secure random API key."""
    return "rgv_" + secrets.token_urlsafe(32)


def create_api_key(owner: str = "anonymous", org_id: str = "default",
                   name: str = "", scopes: str = "read,write",
                   provider: str = "all", expires_at: Optional[str] = None) -> str:
    """
    Create a new API key in the database.

    Args:
        provider: "all" for universal key, or specific provider prefix ("openai", "anthropic", etc.)
    Returns the plaintext key (shown only once).
    """
    key = generate_api_key()
    key_hash = _hash_key(key)
    db = _get_db()
    db.execute(
        "INSERT INTO api_keys (key_hash, owner, org_id, name, provider, scopes, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (key_hash, owner, org_id, name, provider, scopes, expires_at),
    )
    db.commit()
    return key


def revoke_api_key(key_id: int) -> bool:
    """Revoke (deactivate) an API key by ID."""
    db = _get_db()
    db.execute("UPDATE api_keys SET is_active = 0 WHERE id = ?", (key_id,))
    db.commit()
    return db.total_changes > 0


def list_api_keys(org_id: Optional[str] = None) -> list:
    """List all API keys (without hashes). Optionally filter by org_id."""
    db = _get_db()
    if org_id:
        rows = db.execute(
            "SELECT id, owner, org_id, name, is_active, created_at, expires_at, scopes FROM api_keys WHERE org_id = ?",
            (org_id,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, owner, org_id, name, is_active, created_at, expires_at, scopes FROM api_keys"
        ).fetchall()
    return [
        {
            "id": r["id"],
            "owner": r["owner"],
            "org_id": r["org_id"],
            "name": r["name"],
            "is_active": bool(r["is_active"]),
            "created_at": r["created_at"],
            "expires_at": r["expires_at"],
            "scopes": r["scopes"],
        }
        for r in rows
    ]
