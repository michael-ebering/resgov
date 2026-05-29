"""
ResGov — License Key Management
One-time-purchase license validation with DB-backed storage.

License tiers:
  community  — max 5 agents, 1 org, lifetime, ~250€ one-time
  pro        — max 50 agents, 5 orgs, 1 year, ~990€ one-time
  enterprise — unlimited, custom pricing
"""
import os
import secrets
import hashlib
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import HTTPException

from .middleware import _local

# ── License tier definitions ──────────────────────────────────────────────

LICENSE_TIERS = {
    "community": {
        "max_agents": 5,
        "max_orgs": 1,
        "max_requests_per_day": 10_000,
        "duration_days": None,  # lifetime
    },
    "pro": {
        "max_agents": 50,
        "max_orgs": 5,
        "max_requests_per_day": 100_000,
        "duration_days": 365,
    },
    "enterprise": {
        "max_agents": -1,  # unlimited
        "max_orgs": -1,
        "max_requests_per_day": -1,
        "duration_days": 365,
    },
}


def _get_db() -> sqlite3.Connection:
    if not hasattr(_local, "connection") or _local.connection is None:
        from .middleware import get_db
        _local.connection = get_db()
    return _local.connection


def _hash_license(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def init_license_table():
    """Create the license_keys table if it doesn't exist."""
    db = _get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS license_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_hash TEXT NOT NULL UNIQUE,
            product TEXT NOT NULL DEFAULT 'community',
            max_agents INTEGER NOT NULL DEFAULT 5,
            max_orgs INTEGER NOT NULL DEFAULT 1,
            max_requests_per_day INTEGER NOT NULL DEFAULT 10000,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            activated_at TEXT,
            valid_until TEXT,
            owner_email TEXT DEFAULT '',
            machine_id TEXT DEFAULT ''
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_license_hash ON license_keys(key_hash)
    """)
    db.commit()


def generate_license_key(product: str = "community") -> str:
    """Generate a new license key.
    Format: rgf_<product>_<random>
    Example: rgf_community_aBcDeFgHiJkLmNoPqRsTuVwXyZ123456
    """
    prefix = f"rgf_{product}_"
    random_part = secrets.token_urlsafe(32)
    return prefix + random_part


def create_license(product: str = "community", owner_email: str = "",
                   machine_id: str = "", tier_overrides: Optional[dict] = None) -> str:
    """Create a new license key in the database. Returns the plaintext key."""
    key = generate_license_key(product)
    key_hash = _hash_license(key)
    tier = LICENSE_TIERS.get(product, LICENSE_TIERS["community"])

    max_agents = tier_overrides.get("max_agents", tier["max_agents"]) if tier_overrides else tier["max_agents"]
    max_orgs = tier_overrides.get("max_orgs", tier["max_orgs"]) if tier_overrides else tier["max_orgs"]
    max_rpd = tier_overrides.get("max_requests_per_day", tier["max_requests_per_day"]) if tier_overrides else tier["max_requests_per_day"]

    valid_until = None
    if tier["duration_days"]:
        valid_until = (datetime.now(timezone.utc) + timedelta(days=tier["duration_days"])).isoformat()

    db = _get_db()
    db.execute(
        """INSERT INTO license_keys
           (key_hash, product, max_agents, max_orgs, max_requests_per_day,
            valid_until, owner_email, machine_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (key_hash, product, max_agents, max_orgs, max_rpd, valid_until, owner_email, machine_id),
    )
    db.commit()
    return key


def validate_license(license_key: str) -> dict:
    """Validate a license key. Returns license info dict or raises HTTPException."""
    if not license_key:
        raise HTTPException(status_code=401, detail="Missing license key")

    key_hash = _hash_license(license_key)
    db = _get_db()
    row = db.execute(
        "SELECT * FROM license_keys WHERE key_hash = ? AND is_active = 1",
        (key_hash,),
    ).fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="Invalid license key")

    # Check expiry
    if row["valid_until"]:
        try:
            expiry = datetime.fromisoformat(row["valid_until"])
            if datetime.now(timezone.utc) > expiry:
                raise HTTPException(status_code=401, detail="License expired")
        except (ValueError, TypeError):
            pass

    return {
        "product": row["product"],
        "max_agents": row["max_agents"],
        "max_orgs": row["max_orgs"],
        "max_requests_per_day": row["max_requests_per_day"],
        "valid_until": row["valid_until"],
        "owner_email": row["owner_email"],
    }


def get_active_license() -> Optional[dict]:
    """Get the currently active license (first active one). Returns None if no license."""
    db = _get_db()
    row = db.execute(
        "SELECT * FROM license_keys WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None

    # Check expiry
    if row["valid_until"]:
        try:
            expiry = datetime.fromisoformat(row["valid_until"])
            if datetime.now(timezone.utc) > expiry:
                return None
        except (ValueError, TypeError):
            pass

    return {
        "product": row["product"],
        "max_agents": row["max_agents"],
        "max_orgs": row["max_orgs"],
        "max_requests_per_day": row["max_requests_per_day"],
        "valid_until": row["valid_until"],
        "owner_email": row["owner_email"],
    }


def check_agent_limit(org_id: str) -> bool:
    """Check if the current license allows creating another agent for this org."""
    license_info = get_active_license()
    if not license_info:
        return True  # No license = dev mode, allow all

    max_agents = license_info["max_agents"]
    if max_agents == -1:
        return True  # Unlimited

    db = _get_db()
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM agents WHERE org_id = ?",
        (org_id,),
    ).fetchone()
    return row["cnt"] < max_agents


def list_licenses() -> list:
    """List all licenses (admin only)."""
    db = _get_db()
    rows = db.execute(
        "SELECT id, product, max_agents, max_orgs, max_requests_per_day, "
        "is_active, created_at, activated_at, valid_until, owner_email "
        "FROM license_keys ORDER BY id DESC"
    ).fetchall()
    return [
        {
            "id": r["id"],
            "product": r["product"],
            "max_agents": r["max_agents"],
            "max_orgs": r["max_orgs"],
            "max_requests_per_day": r["max_requests_per_day"],
            "is_active": bool(r["is_active"]),
            "created_at": r["created_at"],
            "activated_at": r["activated_at"],
            "valid_until": r["valid_until"],
            "owner_email": r["owner_email"],
        }
        for r in rows
    ]


def revoke_license(license_id: int) -> bool:
    """Revoke (deactivate) a license by ID."""
    db = _get_db()
    db.execute("UPDATE license_keys SET is_active = 0 WHERE id = ?", (license_id,))
    db.commit()
    return db.total_changes > 0


def activate_license(license_key: str, machine_id: str = "") -> dict:
    """Activate a license on this machine. Sets activated_at and optional machine_id."""
    key_hash = _hash_license(license_key)
    db = _get_db()
    row = db.execute(
        "SELECT * FROM license_keys WHERE key_hash = ?", (key_hash,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="License key not found")

    now = datetime.now(timezone.utc).isoformat()
    if machine_id:
        db.execute(
            "UPDATE license_keys SET activated_at = ?, machine_id = ? WHERE key_hash = ?",
            (now, machine_id, key_hash),
        )
    else:
        db.execute(
            "UPDATE license_keys SET activated_at = ? WHERE key_hash = ?",
            (now, key_hash),
        )
    db.commit()
    return validate_license(license_key)
