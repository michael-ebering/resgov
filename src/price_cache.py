"""
ResGov — Price Cache Service.

Fetches model prices from OpenRouter /models API and caches them locally.
Falls back to DEFAULT_PRICE_TABLE from api.py if the API is unreachable.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from .models import get_db

logger = logging.getLogger("resgov.price_cache")

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_TTL_HOURS = 6


def fetch_prices_from_openrouter() -> dict:
    """Fetch current model prices from OpenRouter.

    Returns:
        Dict mapping model_id -> {"input": float, "output": float}
        Empty dict on failure.
    """
    api_key = os.environ.get("RESGOV_UPSTREAM_API_KEY", "")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        r = httpx.get(OPENROUTER_MODELS_URL, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning(f"OpenRouter /models fetch failed: {e}")
        return {}

    prices = {}
    for model in data.get("data", []):
        model_id = model.get("id", "")
        pricing = model.get("pricing", {})
        if not model_id or not pricing:
            continue
        try:
            input_price = float(pricing.get("input", 0))
            output_price = float(pricing.get("output", 0))
            if input_price > 0 or output_price > 0:
                prices[model_id] = {"input": input_price, "output": output_price}
        except (ValueError, TypeError):
            continue

    logger.info(f"Fetched prices for {len(prices)} models from OpenRouter")
    return prices


def update_price_cache(prices: dict) -> int:
    """Write fetched prices into the local SQLite cache.

    Args:
        prices: Dict mapping model_id -> {"input": float, "output": float}

    Returns:
        Number of models updated
    """
    if not prices:
        return 0

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    updated = 0
    for model_id, pricing in prices.items():
        db.execute(
            """INSERT INTO price_cache (model, input_price, output_price, fetched_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(model) DO UPDATE SET
                   input_price = excluded.input_price,
                   output_price = excluded.output_price,
                   fetched_at = excluded.fetched_at""",
            (model_id, pricing["input"], pricing["output"], now),
        )
        updated += 1
    db.commit()
    return updated


def get_cached_price(model: str) -> Optional[dict]:
    """Get cached price for a model.

    Returns:
        {"input": float, "output": float} or None if not cached or stale
    """
    db = get_db()
    row = db.execute(
        "SELECT input_price, output_price, fetched_at FROM price_cache WHERE model = ?",
        (model,),
    ).fetchone()
    if not row:
        return None

    # Check staleness
    try:
        fetched = datetime.fromisoformat(row["fetched_at"])
        age_hours = (datetime.now(timezone.utc) - fetched).total_seconds() / 3600
        if age_hours > CACHE_TTL_HOURS * 2:  # Hard expiry at 2x TTL
            return None
    except (ValueError, TypeError):
        return None

    return {"input": row["input_price"], "output": row["output_price"]}


def refresh_price_cache() -> dict:
    """Full refresh cycle: fetch from OpenRouter, update cache, return summary.

    Returns:
        {"fetched": int, "updated": int, "status": "ok"|"error"}
    """
    prices = fetch_prices_from_openrouter()
    if not prices:
        return {"fetched": 0, "updated": 0, "status": "error"}
    updated = update_price_cache(prices)
    return {"fetched": len(prices), "updated": updated, "status": "ok"}


def _get_merged_price_table() -> dict:
    """Get the merged price table: DB cache entries override hardcoded defaults."""
    db = get_db()
    rows = db.execute("SELECT model, input_price, output_price FROM price_cache").fetchall()
    if not rows:
        return {}

    # Import DEFAULT_PRICE_TABLE lazily to avoid circular import
    from .api import DEFAULT_PRICE_TABLE
    merged = dict(DEFAULT_PRICE_TABLE)
    for row in rows:
        merged[row["model"]] = {"input": row["input_price"], "output": row["output_price"]}
    return merged
