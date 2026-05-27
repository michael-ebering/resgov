"""
ResGov — Budget Reset Scheduler
Automatically resets daily (00:00 UTC) and monthly (1st of month 00:00 UTC) budgets.
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("resgov.scheduler")

_scheduler: BackgroundScheduler | None = None


def _reset_daily():
    from .models import reset_daily_budgets
    try:
        reset_daily_budgets()
        logger.info("Daily budgets reset automatically")
    except Exception as e:
        logger.error(f"Daily budget reset failed: {e}")


def _reset_monthly():
    from .models import reset_monthly_budgets
    try:
        reset_monthly_budgets()
        logger.info("Monthly budgets reset automatically")
    except Exception as e:
        logger.error(f"Monthly budget reset failed: {e}")


def _expire_reserved():
    """Auto-finalize expired reservations (crash recovery)."""
    from .engine import BudgetEngine
    from .middleware import get_db
    from datetime import datetime, timezone

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    expired = db.execute(
        "SELECT * FROM reserved_budgets WHERE status = 'active' AND expires_at < ?",
        (now,),
    ).fetchall()

    engine = BudgetEngine()
    for res in expired:
        try:
            engine.finalize_budget(res["agent_id"], res["reserved_cost"], 0.0)
            db.execute(
                "UPDATE reserved_budgets SET status = 'expired' WHERE id = ?",
                (res["id"],),
            )
            logger.info(f"Expired reservation auto-finalized: agent={res['agent_id']}, cost={res['reserved_cost']}")
        except Exception as e:
            logger.error(f"Failed to expire reservation {res['id']}: {e}")

    if expired:
        logger.info(f"Expired {len(expired)} stale reservations")


def start_scheduler():
    """Start the background scheduler. Called during app startup."""
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _reset_daily,
        trigger=CronTrigger(hour=0, minute=0),
        id="reset_daily",
        name="Reset daily budgets at midnight UTC",
    )
    _scheduler.add_job(
        _reset_monthly,
        trigger=CronTrigger(day=1, hour=0, minute=0),
        id="reset_monthly",
        name="Reset monthly budgets on 1st of month",
    )
    _scheduler.add_job(
        _expire_reserved,
        trigger="interval", minutes=2,
        id="expire_reserved",
        name="Auto-finalize expired reservations every 2 minutes",
    )
    _scheduler.start()
    logger.info("Scheduler started → daily@00:00 UTC, monthly@1st@00:00 UTC, expire@2min")


def stop_scheduler():
    """Stop the scheduler. Called during app shutdown."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")
