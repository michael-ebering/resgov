"""
ResGov — Database Models
SQLite with WAL mode for concurrent access
"""
import sqlite3
import os
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.environ.get("RESGOV_DB_PATH", "/data/resgov.db")


def get_db() -> sqlite3.Connection:
    """Get a database connection with WAL mode and row factory."""
    db_path = os.environ.get("RESGOV_DB_PATH", "/data/resgov.db")
    db = sqlite3.connect(db_path, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.row_factory = sqlite3.Row
    return db


def init_db(db: Optional[sqlite3.Connection] = None):
    """Initialize the database schema."""
    if db is None:
        db = get_db()

    db.executescript("""
        -- Organizations / Teams (multi-tenant)
        CREATE TABLE IF NOT EXISTS orgs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- Agents (registered AI agents)
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL DEFAULT 'default',
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'paused', 'revoked')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (org_id) REFERENCES orgs(id)
        );

        -- Budgets (per-agent spending limits)
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT NOT NULL,
            period TEXT NOT NULL CHECK(period IN ('daily', 'monthly', 'total')),
            limit_amount REAL NOT NULL CHECK(limit_amount > 0),
            spent_amount REAL NOT NULL DEFAULT 0.0 CHECK(spent_amount >= 0),
            currency TEXT NOT NULL DEFAULT 'USD',
            reset_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(agent_id, period),
            FOREIGN KEY (agent_id) REFERENCES agents(id)
        );

        -- Resource bookings (audit trail)
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT NOT NULL,
            resource_type TEXT NOT NULL CHECK(resource_type IN ('api_call', 'compute', 'storage', 'custom', 'llm_call')),
            action TEXT NOT NULL,
            cost REAL NOT NULL DEFAULT 0.0,
            metadata TEXT DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'success' CHECK(status IN ('success', 'denied', 'error', 'reserved')),
            denial_reason TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (agent_id) REFERENCES agents(id)
        );

        -- Indexes for performance
        CREATE INDEX IF NOT EXISTS idx_bookings_agent_id ON bookings(agent_id);
        CREATE INDEX IF NOT EXISTS idx_bookings_created_at ON bookings(created_at);
        CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);
        CREATE INDEX IF NOT EXISTS idx_agents_org_id ON agents(org_id);
    """)

    # Ensure default org exists
    db.execute(
        "INSERT OR IGNORE INTO orgs (id, name) VALUES (?, ?)",
        ("default", "Default Organization")
    )

    db.commit()


def reset_daily_budgets(db: Optional[sqlite3.Connection] = None):
    """Reset all daily budgets (called by cron/scheduler)."""
    if db is None:
        db = get_db()
    db.execute(
        "UPDATE budgets SET spent_amount = 0.0, reset_at = datetime('now') WHERE period = 'daily'"
    )
    db.commit()


def reset_monthly_budgets(db: Optional[sqlite3.Connection] = None):
    """Reset all monthly budgets."""
    if db is None:
        db = get_db()
    db.execute(
        "UPDATE budgets SET spent_amount = 0.0, reset_at = datetime('now') WHERE period = 'monthly'"
    )
    db.commit()
