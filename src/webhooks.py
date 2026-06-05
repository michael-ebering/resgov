"""
ResGov — Webhook Management
CRUD for webhook subscriptions with Discord + Slack support.
"""
import os
import json
import sqlite3
import hashlib
import hmac
import secrets
import urllib.request
import urllib.error
import logging
from datetime import datetime, timezone
from typing import Optional, List

logger = logging.getLogger("resgov.webhooks")

WEBHOOK_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS webhooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    secret TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL DEFAULT 'discord',
    events TEXT NOT NULL DEFAULT '["*"]',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_triggered TEXT,
    last_status TEXT DEFAULT 'pending',
    failure_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_webhooks_active ON webhooks(is_active);
"""


def init_webhooks_table(db: sqlite3.Connection):
    """Create webhooks table if not exists."""
    db.executescript(WEBHOOK_TABLE_SQL)
    db.commit()


def create_webhook(db: sqlite3.Connection, url: str, name: str = "",
                   hook_type: str = "discord", events: list = None,
                   secret: str = "") -> dict:
    """Register a new webhook. Returns the webhook dict with plaintext secret."""
    if events is None:
        events = ["*"]
    if not secret:
        secret = secrets.token_hex(16)

    events_json = json.dumps(events)  # type: ignore[arg-type]
    db.execute(
        "INSERT INTO webhooks (name, url, secret, type, events) VALUES (?, ?, ?, ?, ?)",
        (name, url, secret, hook_type, events_json),
    )
    db.commit()
    row = db.execute("SELECT * FROM webhooks WHERE id = last_insert_rowid()").fetchone()
    return _row_to_dict(row)


def list_webhooks(db: sqlite3.Connection, active_only: bool = False) -> list:
    """List all webhooks (without secrets)."""
    if active_only:
        rows = db.execute(
            "SELECT id, name, url, type, events, is_active, created_at, last_triggered, last_status, failure_count "
            "FROM webhooks WHERE is_active = 1 ORDER BY id"
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, name, url, type, events, is_active, created_at, last_triggered, last_status, failure_count "
            "FROM webhooks ORDER BY id"
        ).fetchall()
    return [
        {
            "id": r[0], "name": r[1], "url": r[2], "type": r[3],
            "events": json.loads(r[4]), "is_active": bool(r[5]),
            "created_at": r[6], "last_triggered": r[7],
            "last_status": r[8], "failure_count": r[9],
        }
        for r in rows
    ]


def get_webhook(db: sqlite3.Connection, webhook_id: int) -> Optional[dict]:
    """Get a single webhook by ID (with secret for internal use)."""
    row = db.execute("SELECT * FROM webhooks WHERE id = ?", (webhook_id,)).fetchone()
    if not row:
        return None
    return _row_to_dict(row, include_secret=True)


def delete_webhook(db: sqlite3.Connection, webhook_id: int) -> bool:
    """Delete a webhook by ID."""
    db.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
    db.commit()
    return db.total_changes > 0


def update_webhook(db: sqlite3.Connection, webhook_id: int, **kwargs) -> Optional[dict]:
    """Update webhook fields."""
    allowed = {"name", "url", "type", "events", "is_active"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return None
    if "events" in updates:
        updates["events"] = json.dumps(updates["events"])

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [webhook_id]
    db.execute(f"UPDATE webhooks SET {set_clause} WHERE id = ?", values)
    db.commit()
    return get_webhook(db, webhook_id)


def _row_to_dict(row, include_secret=False) -> dict:
    d = {
        "id": row[0], "name": row[1], "url": row[2],
        "type": row[4], "events": json.loads(row[5]) if row[5] else ["*"],
        "is_active": bool(row[6]), "created_at": row[7],
        "last_triggered": row[8], "last_status": row[9],
        "failure_count": row[10] if len(row) > 10 else 0,
    }
    if include_secret:
        d["secret"] = row[3]
    return d


def send_webhook(db: sqlite3.Connection, event: str, data: dict):
    """Send event to all matching active webhooks."""
    rows = db.execute(
        "SELECT id, url, secret, type, events FROM webhooks WHERE is_active = 1"
    ).fetchall()

    for row in rows:
        webhook_id, url, secret, hook_type, events_json = row
        events = json.loads(events_json) if events_json else ["*"]
        if "*" not in events and event not in events:
            continue

        payload = _build_payload(event, data, hook_type)
        signature = hmac.new(secret.encode(), json.dumps(payload).encode(), "sha256").hexdigest()

        try:
            body = json.dumps(payload).encode()
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-ResGov-Event": event,
                    "X-ResGov-Signature": f"sha256={signature}",
                    "User-Agent": "ResGov-Webhook/1.0",
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
            db.execute(
                "UPDATE webhooks SET last_triggered = ?, last_status = 'ok', failure_count = 0 WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), webhook_id),
            )
            logger.info(f"Webhook {webhook_id} sent: {event}")
        except Exception as e:
            db.execute(
                "UPDATE webhooks SET last_status = 'error', failure_count = failure_count + 1 WHERE id = ?",
                (webhook_id,),
            )
            logger.warning(f"Webhook {webhook_id} failed: {event} → {e}")

    db.commit()


def _build_payload(event: str, data: dict, hook_type: str) -> dict:
    """Build webhook payload based on type (discord vs slack vs generic)."""
    timestamp = datetime.now(timezone.utc).isoformat()

    if hook_type == "discord":
        # Discord expects { embeds: [...] } format
        color = _event_color(event)
        return {
            "embeds": [{
                "title": f"ResGov: {event}",
                "description": _event_description(event, data),
                "color": color,
                "fields": [{"name": k, "value": str(v)[:1024], "inline": True} for k, v in data.items()],
                "timestamp": timestamp,
                "footer": {"text": f"ResGov v0.4.4 • {event}"},
            }]
        }
    elif hook_type == "slack":
        # Slack expects { blocks: [...] } format
        return {
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"ResGov: {event}"},
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*{k}:*\n{str(v)[:512]}"}
                        for k, v in data.items()
                    ],
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"ResGov v0.4.4 • {timestamp}"},
                    ],
                },
            ]
        }
    else:
        # Generic JSON webhook
        return {
            "event": event,
            "data": data,
            "timestamp": timestamp,
            "source": "resgov",
            "version": "0.4.4",
        }


def _event_color(event: str) -> int:
    """Discord embed color based on event type."""
    if "denied" in event or "error" in event or "revoked" in event:
        return 0xFF4444  # red
    elif "success" in event or "registered" in event or "finalized" in event:
        return 0x44FF44  # green
    elif "warning" in event or "exceeded" in event:
        return 0xFFAA00  # orange
    return 0xF97316  # ResGov orange


def _event_description(event: str, data: dict) -> str:
    """Human-readable event description."""
    agent = data.get("agent_id", data.get("email", "unknown"))
    descriptions = {
        "agent.registered": f"Agent **{agent}** has been registered.",
        "booking.success": f"Booking confirmed for **{agent}**.",
        "booking.denied": f"Booking denied for **{agent}**: {data.get('reason', 'unknown')}",
        "budget.updated": f"Budget updated for **{agent}**.",
        "budget.reserved": f"Budget reserved for **{agent}**.",
        "budget.reserve_denied": f"Budget reservation denied for **{agent}**.",
        "budget.finalized": f"Budget finalized for **{agent}**.",
        "agent.revoked": f"Agent **{agent}** has been revoked.",
        "lead.created": f"New lead registered: **{agent}**.",
    }
    return descriptions.get(event, f"Event: {event}")
