"""
ResGov — Budget Engine v2
Row-level locking, retries, webhook notifications, soft-delete.
"""
import sqlite3
import json
import os
import time
import logging
from datetime import datetime, timezone
from typing import Optional

from .models import get_db
from .middleware import get_db as _get_db, get_transaction, close_db

logger = logging.getLogger("resgov.engine")

# --- Webhook Configuration ---

WEBHOOK_URL = os.environ.get("RESGOV_WEBHOOK_URL", "")
WEBHOOK_SECRET = os.environ.get("RESGOV_WEBHOOK_SECRET", "")


def _send_webhook(event: str, data: dict):
    """Send webhook notification (async fire-and-forget)."""
    if not WEBHOOK_URL:
        return

    import urllib.request
    import urllib.error

    payload = json.dumps({
        "event": event,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }).encode()

    try:
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-ResGov-Event": event,
                "X-ResGov-Signature": WEBHOOK_SECRET,
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
        logger.info(f"Webhook sent: {event}")
    except Exception as e:
        logger.warning(f"Webhook failed: {event} → {e}")


class BudgetEngine:
    """
    Resource booking, quota enforcement, cost tracking.
    Thread-safe with row-level locking via SQLite BEGIN IMMEDIATE.
    """

    MAX_RETRIES = 3
    RETRY_DELAY = 0.1  # seconds

    def _execute_with_retry(self, operation, description="operation"):
        """
        Execute a database operation with retry logic for SQLite locks.
        Uses BEGIN IMMEDIATE for write locking.
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                with get_transaction() as db:
                    return operation(db)
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < self.MAX_RETRIES - 1:
                    logger.warning(f"DB locked, retry {attempt + 1}/{self.MAX_RETRIES}: {description}")
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                    continue
                raise
            except Exception:
                raise

        raise RuntimeError(f"Max retries exceeded: {description}")

    def register_agent(
        self,
        agent_id: str,
        name: str,
        org_id: str = "default",
        description: str = "",
        daily_limit: float = 5.0,
        monthly_limit: float = 100.0,
    ) -> dict:
        """Register a new agent with default budgets."""

        def _op(db):
            now = datetime.now(timezone.utc).isoformat()

            db.execute(
                "INSERT OR IGNORE INTO orgs (id, name) VALUES (?, ?)",
                (org_id, org_id),
            )

            db.execute(
                """INSERT OR REPLACE INTO agents (id, org_id, name, description, status, created_at)
                   VALUES (?, ?, ?, ?, 'active', ?)""",
                (agent_id, org_id, name, description, now),
            )

            for period, limit in [("daily", daily_limit), ("monthly", monthly_limit)]:
                db.execute(
                    """INSERT OR REPLACE INTO budgets (agent_id, period, limit_amount, spent_amount, updated_at)
                       VALUES (?, ?, ?, 0.0, ?)""",
                    (agent_id, period, limit, now),
                )

            return self.get_agent(db, agent_id)

        result = self._execute_with_retry(_op, "register_agent")
        _send_webhook("agent.registered", {"agent_id": agent_id, "name": name})
        return result

    def get_agent(self, db=None, agent_id: str = None) -> Optional[dict]:
        """Get agent details with current budget status."""
        if agent_id is None:
            # Called without db, just return None (compat)
            return None

        if db is None:
            return self._fetch_agent(get_db(), agent_id)
        return self._fetch_agent(db, agent_id)

    def _fetch_agent(self, db, agent_id: str) -> Optional[dict]:
        agent = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if not agent:
            return None

        budgets = db.execute(
            "SELECT * FROM budgets WHERE agent_id = ?", (agent_id,)
        ).fetchall()

        return {
            "id": agent["id"],
            "org_id": agent["org_id"],
            "name": agent["name"],
            "description": agent["description"],
            "status": agent["status"],
            "created_at": agent["created_at"],
            "budgets": [
                {
                    "period": b["period"],
                    "limit": b["limit_amount"],
                    "spent": b["spent_amount"],
                    "remaining": round(b["limit_amount"] - b["spent_amount"], 4),
                    "currency": b["currency"],
                    "reset_at": b["reset_at"],
                }
                for b in budgets
            ],
        }

    def book(
        self,
        agent_id: str,
        resource_type: str = "api_call",
        action: str = "execute",
        cost: float = 0.0,
        metadata: Optional[dict] = None,
    ) -> dict:
        """Book a resource. Uses row-level locking to prevent race conditions."""

        if cost < 0:
            return {
                "status": "denied",
                "reason": "invalid_cost",
                "message": "Cost cannot be negative. Use positive values only.",
            }

        now = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(metadata or {})

        def _op(db):
            # Agent check
            agent = db.execute(
                "SELECT * FROM agents WHERE id = ?", (agent_id,)
            ).fetchone()

            if not agent:
                return {
                    "status": "denied",
                    "reason": "agent_not_found",
                    "message": f"Agent '{agent_id}' is not registered.",
                }

            if agent["status"] != "active":
                return {
                    "status": "denied",
                    "reason": f"agent_{agent['status']}",
                    "message": f"Agent '{agent_id}' is {agent['status']}.",
                }

            # Budget check with row-level lock (SELECT within BEGIN IMMEDIATE)
            budgets = db.execute(
                "SELECT * FROM budgets WHERE agent_id = ?", (agent_id,)
            ).fetchall()

            for budget in budgets:
                projected = budget["spent_amount"] + cost
                if projected > budget["limit_amount"]:
                    denial_reason = f"{budget['period']}_budget_exceeded"
                    db.execute(
                        """INSERT INTO bookings (agent_id, resource_type, action, cost, metadata, status, denial_reason, created_at)
                           VALUES (?, ?, ?, ?, ?, 'denied', ?, ?)""",
                        (agent_id, resource_type, action, cost, meta_json, denial_reason, now),
                    )

                    remaining = round(budget["limit_amount"] - budget["spent_amount"], 4)
                    return {
                        "status": "denied",
                        "reason": denial_reason,
                        "message": f"{budget['period'].capitalize()} budget exceeded. "
                        f"Limit: ${budget['limit_amount']:.2f}, "
                        f"Spent: ${budget['spent_amount']:.2f}, "
                        f"Remaining: ${remaining:.2f}, "
                        f"Requested: ${cost:.2f}",
                        "budget_period": budget["period"],
                        "remaining": remaining,
                    }

            # All budgets OK — deduct
            for budget in budgets:
                db.execute(
                    "UPDATE budgets SET spent_amount = spent_amount + ?, updated_at = ? WHERE id = ?",
                    (cost, now, budget["id"]),
                )

            # Log successful booking
            db.execute(
                """INSERT INTO bookings (agent_id, resource_type, action, cost, metadata, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'success', ?)""",
                (agent_id, resource_type, action, cost, meta_json, now),
            )

            # Build response
            remaining_budgets = []
            for budget in budgets:
                new_spent = budget["spent_amount"] + cost
                remaining_budgets.append({
                    "period": budget["period"],
                    "remaining": round(budget["limit_amount"] - new_spent, 4),
                })

            return {
                "status": "success",
                "message": "Resource booked successfully.",
                "cost": cost,
                "budgets": remaining_budgets,
            }

        result = self._execute_with_retry(_op, "book")

        if result["status"] == "success":
            _send_webhook("booking.success", {"agent_id": agent_id, "cost": cost, "action": action})
        else:
            _send_webhook("booking.denied", {"agent_id": agent_id, "reason": result["reason"]})

        return result

    def get_usage(self, agent_id: str, limit: int = 100) -> dict:
        """Get usage statistics for an agent."""
        db = get_db()
        agent = self._fetch_agent(db, agent_id)
        if not agent:
            return {"error": "agent_not_found"}

        bookings = db.execute(
            """SELECT * FROM bookings WHERE agent_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (agent_id, limit),
        ).fetchall()

        total_spent = db.execute(
            "SELECT COALESCE(SUM(cost), 0) as total FROM bookings WHERE agent_id = ? AND status = 'success'",
            (agent_id,),
        ).fetchone()["total"]

        total_denied = db.execute(
            "SELECT COUNT(*) as count FROM bookings WHERE agent_id = ? AND status = 'denied'",
            (agent_id,),
        ).fetchone()["count"]

        return {
            "agent": agent,
            "total_spent": round(total_spent, 4),
            "total_denied": total_denied,
            "recent_bookings": [
                {
                    "id": b["id"],
                    "resource_type": b["resource_type"],
                    "action": b["action"],
                    "cost": b["cost"],
                    "status": b["status"],
                    "denial_reason": b["denial_reason"],
                    "created_at": b["created_at"],
                }
                for b in bookings
            ],
        }

    def get_audit_log(
        self,
        org_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 100,
    ) -> dict:
        """Get paginated audit trail."""
        db = get_db()

        # Count total
        if org_id:
            total = db.execute(
                "SELECT COUNT(*) as cnt FROM bookings b JOIN agents a ON b.agent_id = a.id WHERE a.org_id = ?",
                (org_id,),
            ).fetchone()["cnt"]
        else:
            total = db.execute("SELECT COUNT(*) as cnt FROM bookings").fetchone()["cnt"]

        # Paginated query
        offset = (page - 1) * page_size
        if org_id:
            rows = db.execute(
                """SELECT b.*, a.org_id FROM bookings b
                   JOIN agents a ON b.agent_id = a.id
                   WHERE a.org_id = ?
                   ORDER BY b.created_at DESC LIMIT ? OFFSET ?""",
                (org_id, page_size, offset),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM bookings ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (page_size, offset),
            ).fetchall()

        return {
            "data": [
                {
                    "id": r["id"],
                    "agent_id": r["agent_id"],
                    "resource_type": r["resource_type"],
                    "action": r["action"],
                    "cost": r["cost"],
                    "status": r["status"],
                    "denial_reason": r["denial_reason"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size,
        }

    def set_budget(self, agent_id: str, period: str, limit_amount: float) -> dict:
        """Set or update a budget for an agent."""

        def _op(db):
            now = datetime.now(timezone.utc).isoformat()
            db.execute(
                """INSERT INTO budgets (agent_id, period, limit_amount, spent_amount, updated_at)
                   VALUES (?, ?, ?, 0.0, ?)
                   ON CONFLICT(agent_id, period) DO UPDATE SET limit_amount = ?, updated_at = ?""",
                (agent_id, period, limit_amount, now, limit_amount, now),
            )
            return self._fetch_agent(db, agent_id)

        result = self._execute_with_retry(_op, "set_budget")
        _send_webhook("budget.updated", {"agent_id": agent_id, "period": period, "limit": limit_amount})
        return result

    def delete_agent(self, agent_id: str) -> dict:
        """Soft-delete an agent (mark as revoked, keep audit trail)."""
        def _op(db):
            db.execute(
                "UPDATE agents SET status = 'revoked' WHERE id = ?",
                (agent_id,),
            )
            affected = db.total_changes
            return {"deleted": affected > 0, "agent_id": agent_id}

        result = self._execute_with_retry(_op, "delete_agent")
        _send_webhook("agent.revoked", {"agent_id": agent_id})
        return result

    def list_agents(self, org_id: Optional[str] = None) -> list:
        """List all non-revoked agents."""
        db = get_db()
        if org_id:
            rows = db.execute(
                "SELECT id FROM agents WHERE org_id = ? AND status != 'revoked'",
                (org_id,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT id FROM agents WHERE status != 'revoked'"
            ).fetchall()

        return [self._fetch_agent(db, r["id"]) for r in rows]

    # --- Proxy Budget Management (Reserve / Finalize Pattern) ---

    def reserve_budget(self, agent_id: str, max_cost: float) -> dict:
        """
        Reserve budget for an LLM proxy call.
        Deducts max_cost immediately (pessimistic).
        Returns reservation info or denial.
        Lock duration: milliseconds (BEGIN IMMEDIATE + UPDATE + COMMIT).
        """
        if max_cost < 0:
            return {
                "status": "denied",
                "reason": "invalid_cost",
                "message": "Max cost cannot be negative.",
            }

        now = datetime.now(timezone.utc).isoformat()

        def _op(db):
            agent = db.execute(
                "SELECT * FROM agents WHERE id = ?", (agent_id,)
            ).fetchone()

            if not agent:
                return {
                    "status": "denied",
                    "reason": "agent_not_found",
                    "message": f"Agent '{agent_id}' is not registered.",
                }

            if agent["status"] != "active":
                return {
                    "status": "denied",
                    "reason": f"agent_{agent['status']}",
                    "message": f"Agent '{agent_id}' is {agent['status']}.",
                }

            budgets = db.execute(
                "SELECT * FROM budgets WHERE agent_id = ?", (agent_id,)
            ).fetchall()

            for budget in budgets:
                projected = budget["spent_amount"] + max_cost
                if projected > budget["limit_amount"]:
                    remaining = round(budget["limit_amount"] - budget["spent_amount"], 4)
                    return {
                        "status": "denied",
                        "reason": f"{budget['period']}_budget_exceeded",
                        "message": f"{budget['period'].capitalize()} budget exceeded. "
                        f"Limit: ${budget['limit_amount']:.2f}, "
                        f"Spent: ${budget['spent_amount']:.2f}, "
                        f"Remaining: ${remaining:.2f}, "
                        f"Required: ${max_cost:.2f}",
                        "budget_period": budget["period"],
                        "remaining": remaining,
                    }

            for budget in budgets:
                db.execute(
                    "UPDATE budgets SET spent_amount = spent_amount + ?, updated_at = ? WHERE id = ?",
                    (max_cost, now, budget["id"]),
                )

            db.execute(
                """INSERT INTO bookings (agent_id, resource_type, action, cost, metadata, status, created_at)
                   VALUES (?, 'llm_call', 'proxy_reserve', ?, '{}', 'reserved', ?)""",
                (agent_id, max_cost, now),
            )

            remaining_budgets = []
            for budget in budgets:
                new_spent = budget["spent_amount"] + max_cost
                remaining_budgets.append({
                    "period": budget["period"],
                    "remaining": round(budget["limit_amount"] - new_spent, 4),
                })

            return {
                "status": "reserved",
                "reserved_cost": max_cost,
                "budgets": remaining_budgets,
            }

        result = self._execute_with_retry(_op, "reserve_budget")

        if result["status"] == "reserved":
            _send_webhook("budget.reserved", {"agent_id": agent_id, "max_cost": max_cost})
        else:
            _send_webhook("budget.reserve_denied", {"agent_id": agent_id, "reason": result["reason"]})

        return result

    def finalize_budget(self, agent_id: str, reserved_cost: float, actual_cost: float) -> dict:
        """
        Finalize budget after LLM stream completes.
        Refunds the difference (reserved - actual).
        Creates final audit log entry.
        """
        if actual_cost < 0:
            actual_cost = 0

        refund = round(reserved_cost - actual_cost, 4)
        now = datetime.now(timezone.utc).isoformat()

        def _op(db):
            if refund != 0:
                budgets = db.execute(
                    "SELECT * FROM budgets WHERE agent_id = ?", (agent_id,)
                ).fetchall()
                for budget in budgets:
                    db.execute(
                        "UPDATE budgets SET spent_amount = spent_amount - ?, updated_at = ? WHERE id = ?",
                        (refund, now, budget["id"]),
                    )

            db.execute(
                """INSERT INTO bookings (agent_id, resource_type, action, cost, metadata, status, created_at)
                   VALUES (?, 'llm_call', 'proxy_finalize', ?, ?, 'success', ?)""",
                (agent_id, actual_cost, json.dumps({"reserved": reserved_cost, "refund": refund}), now),
            )

            return {
                "status": "finalized",
                "reserved_cost": reserved_cost,
                "actual_cost": actual_cost,
                "refund": refund,
            }

        result = self._execute_with_retry(_op, "finalize_budget")
        _send_webhook("budget.finalized", {
            "agent_id": agent_id,
            "reserved": reserved_cost,
            "actual": actual_cost,
            "refund": refund,
        })
        return result
