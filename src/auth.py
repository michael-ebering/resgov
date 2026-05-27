"""
ResGov — Authentication & Authorization
API-Key based auth with admin token support.
"""
import os
import secrets
import hashlib
from typing import Optional
from fastapi import Header, HTTPException, Request
from fastapi.security import APIKeyHeader

# --- Configuration ---

# In production, load from env or secrets manager
# Format: "key1:agent1,key2:agent2,..."
API_KEYS_ENV = os.environ.get("RESGOV_API_KEYS", "")
ADMIN_TOKEN = os.environ.get("RESGOV_ADMIN_TOKEN", os.environ.get("RESGOV_ADMIN_KEY", ""))

# Parse API keys: "key:owner,key2:owner2" → {"key": "owner", ...}
API_KEYS: dict[str, str] = {}
if API_KEYS_ENV:
    for pair in API_KEYS_ENV.split(","):
        pair = pair.strip()
        if ":" in pair:
            key, owner = pair.split(":", 1)
            API_KEYS[key.strip()] = owner.strip()
        elif pair:
            API_KEYS[pair] = "anonymous"

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: Optional[str] = None) -> str:
    """
    Verify an API key. Returns the owner identifier.
    Raises 401 if invalid.
    """
    # If no keys configured, allow all (dev mode)
    if not API_KEYS:
        return "dev"

    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")

    # Constant-time comparison to prevent timing attacks
    for valid_key, owner in API_KEYS.items():
        if secrets.compare_digest(api_key, valid_key):
            return owner

    raise HTTPException(status_code=401, detail="Invalid API key")


def verify_admin_token(admin_token: Optional[str] = None) -> None:
    """
    Verify admin token for privileged operations.
    Raises 403 if invalid.
    """
    if not ADMIN_TOKEN:
        # In dev mode without admin token, allow all
        return

    if not admin_token:
        raise HTTPException(status_code=403, detail="Missing X-Admin-Token header")

    if not secrets.compare_digest(admin_token, ADMIN_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid admin token")


def generate_api_key() -> str:
    """Generate a secure random API key."""
    return "rgv_" + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a token for storage (never store plaintext)."""
    return hashlib.sha256(token.encode()).hexdigest()
