"""
ResGov — FastAPI REST API v3
Auth, rate limiting, CORS, Prometheus metrics, LLM proxy, graceful shutdown.
"""
import os
import logging
import json
import math
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Depends, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.responses import StreamingResponse
from pydantic import BaseModel, Field

from .models import init_db, reset_daily_budgets, reset_monthly_budgets
from .engine import BudgetEngine
from .auth import verify_api_key, verify_admin_token, generate_api_key, ADMIN_TOKEN, init_api_keys_table, create_api_key, revoke_api_key, list_api_keys, _get_db
from .middleware import setup_cors, RateLimitMiddleware, RequestLoggingMiddleware, ConnectionPool, logger
from .scheduler import start_scheduler, stop_scheduler

import secrets
from .config import load_rgf_config

RGF_CONFIG = {}

# --- Pydantic Models ---

class AgentRegister(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=256)
    org_id: str = Field(default="default", max_length=128)
    description: str = Field(default="", max_length=1024)
    daily_limit: float = Field(default=5.0, gt=0)
    monthly_limit: float = Field(default=100.0, gt=0)

class BookingRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=128)
    resource_type: str = Field(default="api_call", pattern="^(api_call|compute|storage|custom|llm_call)$")
    action: str = Field(default="execute", max_length=256)
    cost: float = Field(default=0.0, ge=0)
    metadata: Optional[dict] = Field(default=None)

class BudgetUpdate(BaseModel):
    period: str = Field(..., pattern="^(daily|monthly|total)$")
    limit_amount: float = Field(..., gt=0)

# --- Metrics (simple in-memory, Prometheus-compatible) ---

_metrics = {
    "requests_total": 0,
    "bookings_total": 0,
    "bookings_denied_total": 0,
    "errors_total": 0,
}

# --- App Lifespan ---

import httpx

_httpx_client: Optional[httpx.AsyncClient] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup."""
    global _httpx_client
    db_path = os.environ.get("RESGOV_DB_PATH", "/data/resgov.db")
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)

    # Init connection pool (sets DB path for thread-local connections)
    _pool = ConnectionPool(db_path)

    # Init DB
    from .middleware import get_db
    db = get_db()
    init_db(db)
    init_api_keys_table()

    # Start scheduler
    start_scheduler()

    # Init shared httpx client for connection pooling
    _httpx_client = httpx.AsyncClient(timeout=120.0)

    # Load .rgf configuration
    global RGF_CONFIG
    RGF_CONFIG = load_rgf_config()
    logger.info(f"Loaded .rgf config: {RGF_CONFIG}")

    logger.info(f"ResGov started | DB: {db_path}")
    yield

    # Cleanup
    stop_scheduler()
    pool = _pool
    pool.close_all()
    if _httpx_client:
        await _httpx_client.aclose()
        _httpx_client = None
    logger.info("ResGov shutdown complete")

# --- App ---

app = FastAPI(
    title="Resource Governance Framework (RGF)",
    description="Resource Governance Framework (RGF) for Multi-Agent Environments — LLM Proxy + Budget Control + Crash Recovery",
    version="0.4.4",
    lifespan=lifespan,
)

# Middleware (order matters: outermost first)
setup_cors(app)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware)

# --- Dependencies ---

async def require_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    return verify_api_key(x_api_key)

async def require_admin(x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token")):
    verify_admin_token(x_admin_token)

# --- API Endpoints ---

@app.post("/api/v1/agents", status_code=201)
async def register_agent(req: AgentRegister, owner=Depends(require_api_key)):
    """Register a new agent with budgets."""
    engine = BudgetEngine(rgf_config=RGF_CONFIG)
    try:
        agent = engine.register_agent(
            agent_id=req.agent_id,
            name=req.name,
            org_id=req.org_id,
            description=req.description,
            daily_limit=req.daily_limit,
            monthly_limit=req.monthly_limit,
        )
        return agent
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            raise HTTPException(status_code=409, detail=f"Agent '{req.agent_id}' already exists.")
        raise

@app.get("/api/v1/agents/{agent_id}")
async def get_agent(agent_id: str, owner=Depends(require_api_key)):
    """Get agent status and budget."""
    engine = BudgetEngine(rgf_config=RGF_CONFIG)
    agent = engine.get_agent(agent_id=agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    return agent

@app.put("/api/v1/agents/{agent_id}/budget")
async def update_budget(agent_id: str, req: BudgetUpdate, owner=Depends(require_api_key)):
    """Update an agent's budget."""
    engine = BudgetEngine(rgf_config=RGF_CONFIG)
    agent = engine.get_agent(agent_id=agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    return engine.set_budget(agent_id, req.period, req.limit_amount)

@app.delete("/api/v1/agents/{agent_id}")
async def delete_agent(agent_id: str, owner=Depends(require_api_key)):
    """Soft-delete an agent (revoke access, keep audit trail)."""
    engine = BudgetEngine(rgf_config=RGF_CONFIG)
    agent = engine.get_agent(agent_id=agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    return engine.delete_agent(agent_id)

@app.post("/api/v1/book")
async def book_resource(req: BookingRequest, owner=Depends(require_api_key)):
    """
    Book a resource for an agent.
    Returns 200 if approved, 403 if denied.
    """
    _metrics["requests_total"] += 1
    engine = BudgetEngine(rgf_config=RGF_CONFIG)
    result = engine.book(
        agent_id=req.agent_id,
        resource_type=req.resource_type,
        action=req.action,
        cost=req.cost,
        metadata=req.metadata,
    )

    if result["status"] == "success":
        _metrics["bookings_total"] += 1
    else:
        _metrics["bookings_denied_total"] += 1

    if result["status"] == "denied":
        return JSONResponse(status_code=403, content=result)
    return result

@app.get("/api/v1/agents")
async def list_agents(org_id: Optional[str] = None, owner=Depends(require_api_key)):
    """List all active agents. Optionally filter by org_id."""
    engine = BudgetEngine(rgf_config=RGF_CONFIG)
    return engine.list_agents(org_id=org_id)

@app.get("/api/v1/usage/{agent_id}")
async def get_usage(
    agent_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    owner=Depends(require_api_key),
):
    """Get usage statistics for an agent."""
    engine = BudgetEngine(rgf_config=RGF_CONFIG)
    usage = engine.get_usage(agent_id, limit=limit)
    if "error" in usage:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    return usage

@app.get("/api/v1/audit")
async def get_audit(
    org_id: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    owner=Depends(require_api_key),
):
    """Get paginated audit trail. Optionally filter by org_id for tenant isolation."""
    engine = BudgetEngine(rgf_config=RGF_CONFIG)
    return engine.get_audit_log(org_id=org_id, page=page, page_size=page_size)

@app.get("/api/v1/agents/{agent_id}/prediction")
async def get_prediction(
    agent_id: str,
    period: str = Query(default="daily", pattern="^(daily|monthly)$"),
    lookback_hours: int = Query(default=6, ge=1, le=24 * 7),
    owner=Depends(require_api_key),
):
    """Get budget exhaustion prediction for an agent."""
    engine = BudgetEngine(rgf_config=RGF_CONFIG)
    prediction = engine.get_budget_prediction(agent_id, period, lookback_hours)
    if prediction["status"] == "error":
        raise HTTPException(status_code=404, detail=prediction["message"])
    return prediction

@app.get("/api/v1/user/keys")
async def list_user_api_keys(owner_info=Depends(require_api_key)):
    """List API keys belonging to the authenticated user's organization."""
    org_id = owner_info["org_id"]
    return list_api_keys(org_id=org_id)

@app.delete("/api/v1/user/keys/{key_id}")
async def revoke_user_key(key_id: int, owner_info=Depends(require_api_key)):
    """Revoke an API key belonging to the authenticated user's organization."""
    user_org_id = owner_info["org_id"]
    db = _get_db() # Assuming _get_db is accessible or imported here similar to init_db
    key_row = db.execute("SELECT org_id FROM api_keys WHERE id = ?", (key_id,)).fetchone()
    if key_row and key_row['org_id'] == user_org_id:
        if revoke_api_key(key_id):
            return {"status": "ok", "message": f"Key {key_id} revoked."}
    raise HTTPException(status_code=404, detail=f"Key {key_id} not found or not authorized.")

# --- Admin Endpoints (require admin token) ---

@app.post("/api/v1/admin/reset-daily")
async def reset_daily(_=Depends(require_admin)):
    """Reset all daily budgets."""
    reset_daily_budgets()
    return {"status": "ok", "message": "Daily budgets reset."}

@app.post("/api/v1/admin/reset-monthly")
async def reset_monthly(_=Depends(require_admin)):
    """Reset all monthly budgets."""
    reset_monthly_budgets()
    return {"status": "ok", "message": "Monthly budgets reset."}

@app.post("/api/v1/admin/generate-key")
async def gen_key(req: dict, _=Depends(require_admin)):
    """Generate a new API key."""
    key = create_api_key(
        owner=req.get("owner", "anonymous"),
        org_id=req.get("org_id", "default"),
        name=req.get("name", ""),
        scopes=req.get("scopes", "read,write"),
        expires_at=req.get("expires_at"),
    )
    return {"api_key": key, "hint": "Store this key — it won't be shown again."}

@app.get("/api/v1/admin/keys")
async def list_keys(org_id: Optional[str] = None, _=Depends(require_admin)):
    """List all API keys (without secret hashes)."""
    return list_api_keys(org_id=org_id)

@app.delete("/api/v1/admin/keys/{key_id}")
async def revoke_key(key_id: int, _=Depends(require_admin)):
    """Revoke an API key by ID."""
    if revoke_api_key(key_id):
        return {"status": "ok", "message": f"Key {key_id} revoked."}
    raise HTTPException(status_code=404, detail=f"Key {key_id} not found.")


@app.get("/api/v1/admin/price-cache")
async def get_price_cache_status(_=Depends(require_admin)):
    """Get current price cache status."""
    from .models import get_db
    db = get_db()
    count = db.execute("SELECT COUNT(*) as cnt FROM price_cache").fetchone()["cnt"]
    latest = db.execute("SELECT MAX(fetched_at) as latest FROM price_cache").fetchone()["latest"]
    return {"model_count": count, "last_fetched": latest or "never"}

@app.post("/api/v1/admin/price-cache/refresh")
async def trigger_price_cache_refresh(_=Depends(require_admin)):
    """Manually trigger a price cache refresh."""
    from .price_cache import refresh_price_cache
    result = refresh_price_cache()
    return result


# --- Health & Metrics ---

@app.get("/health")
async def health():
    """Health check with DB connectivity verification."""
    db_status = "ok"
    try:
        from .middleware import get_db
        db = get_db()
        db.execute("SELECT 1")
    except Exception as e:
        db_status = f"error: {e}"

    scheduler_status = "ok"
    try:
        from .scheduler import _scheduler
        if _scheduler is None or not _scheduler.running:
            scheduler_status = "stopped"
    except Exception:
        scheduler_status = "unknown"

    status = "ok" if db_status == "ok" and scheduler_status == "ok" else "degraded"
    return {
        "status": status,
        "service": "resgov",
        "version": "0.4.4",
        "db": db_status,
        "scheduler": scheduler_status,
    }

@app.get("/metrics")
async def metrics():
    """Prometheus-compatible metrics."""
    lines = [
        "# HELP resgov_requests_total Total API requests",
        "# TYPE resgov_requests_total counter",
        f'resgov_requests_total {_metrics["requests_total"]}',
        "# HELP resgov_bookings_total Total successful bookings",
        "# TYPE resgov_bookings_total counter",
        f'resgov_bookings_total {_metrics["bookings_total"]}',
        "# HELP resgov_bookings_denied_total Total denied bookings",
        "# TYPE resgov_bookings_denied_total counter",
        f'resgov_bookings_denied_total {_metrics["bookings_denied_total"]}',
    ]
    return Response(content="\n".join(lines), media_type="text/plain")

# --- LLM Proxy (OpenAI/Anthropic compatible) ---

# Price table: cost per token for known models
# Override via RESGOV_PRICE_TABLE env var (JSON)
DEFAULT_PRICE_TABLE = {
    "openai/gpt-4o": {"input": 0.0000025, "output": 0.000010},
    "openai/gpt-4o-mini": {"input": 0.00000015, "output": 0.0000006},
    "openai/gpt-3.5-turbo": {"input": 0.0000005, "output": 0.0000015},
    "anthropic/claude-sonnet-4": {"input": 0.000003, "output": 0.000015},
    "anthropic/claude-haiku-4": {"input": 0.00000025, "output": 0.00000125},
    "deepseek/deepseek-v4-flash": {"input": 0.00000007, "output": 0.00000027},
    "deepseek/deepseek-chat": {"input": 0.00000027, "output": 0.0000011},
    "google/gemini-2.5-flash": {"input": 0.0000001, "output": 0.0000004},
    "google/gemini-2.5-pro": {"input": 0.00000125, "output": 0.000010},
    # GitHub Copilot models (OpenAI-compatible, pricing per GitHub Copilot API)
    "github-copilot/gpt-5.5": {"input": 0.000001, "output": 0.000004},
    "github-copilot/gpt-5.4": {"input": 0.000001, "output": 0.000003},
    "github-copilot/gpt-5.4-mini": {"input": 0.0000005, "output": 0.000002},
    "github-copilot/gpt-5.3-codex": {"input": 0.000001, "output": 0.000003},
    "github-copilot/gpt-5.2": {"input": 0.000001, "output": 0.000003},
    "github-copilot/gpt-5-mini": {"input": 0.0000003, "output": 0.0000012},
    "github-copilot/gpt-4.1": {"input": 0.0000005, "output": 0.000002},
    "github-copilot/claude-opus-4.7": {"input": 0.000015, "output": 0.000075},
    "github-copilot/claude-opus-4.6": {"input": 0.000010, "output": 0.000050},
    "github-copilot/claude-opus-4.5": {"input": 0.000010, "output": 0.000050},
    "github-copilot/copilot-opus-4.6-fast": {"input": 0.000060, "output": 0.000300},
    "github-copilot/claude-opus-4.7": {"input": 0.000015, "output": 0.000075},
    "github-copilot/claude-sonnet-4.6": {"input": 0.000003, "output": 0.000015},
    "github-copilot/claude-sonnet-4.5": {"input": 0.000003, "output": 0.000015},
    "github-copilot/claude-haiku-4.5": {"input": 0.00000025, "output": 0.00000125},
    "github-copilot/gemini-3.5-flash": {"input": 0.0000005, "output": 0.000002},
    "github-copilot/gemini-3.1-pro": {"input": 0.00000125, "output": 0.000010},
    "github-copilot/gemini-3-flash": {"input": 0.0000003, "output": 0.000001},
    "github-copilot/gemini-2.5-pro": {"input": 0.00000125, "output": 0.000010},
    "default": {"input": 0.000001, "output": 0.000003},
}

def _get_price_table() -> dict:
    """Load price table with priority: ENV override > DB cache > DEFAULT_PRICE_TABLE."""
    # 1. ENV override (highest priority)
    raw = os.environ.get("RESGOV_PRICE_TABLE", "")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

    # 2. DB price cache
    try:
        from .price_cache import _get_merged_price_table
        cached = _get_merged_price_table()
        if cached:
            return cached
    except Exception:
        pass

    # 3. Hardcoded fallback
    return DEFAULT_PRICE_TABLE

def _estimate_input_tokens(messages: list) -> int:
    """Estimate token count from messages with content-type awareness.

    Heuristics:
    - English prose: ~4 chars/token
    - German text (more compound words): ~3.2 chars/token
    - JSON/Code (high special-char ratio): ~2.5 chars/token
    - Empty/minimal: 128 token minimum
    """
    text = " ".join(m.get("content", "") for m in messages)
    text_len = len(text)
    if not text_len:
        return 128

    special_ratio = sum(1 for c in text if c in "{[]}()=:;/") / text_len
    german_ratio = sum(1 for c in text.lower() if c in "äöüß") / text_len

    if special_ratio > 0.05:
        return max(text_len // 3, 128)
    elif german_ratio > 0.02:
        return max(int(text_len / 3.2), 128)
    else:
        return max(text_len // 4, 128)


def _estimate_max_cost(model: str, max_tokens: int, price_table: dict,
                        prompt: Optional[str] = None, messages: Optional[list] = None) -> float:
    """Estimate worst-case cost for a request."""
    pricing = price_table.get(model, price_table.get("default", {"input": 0.000001, "output": 0.000003}))
    # Estimate input tokens from messages or prompt string
    if messages:
        input_tokens = _estimate_input_tokens(messages)
    elif prompt:
        input_tokens = _estimate_input_tokens([{"content": prompt}])
    else:
        input_tokens = 512
    input_cost = input_tokens * pricing.get("input", 0.000001)
    output_cost = max_tokens * pricing.get("output", 0.000003)
    return round(input_cost + output_cost, 6)

def _extract_usage_from_chunk(chunk: bytes) -> dict:
    """Try to extract token usage from a streaming chunk (OpenAI format only).

    DEPRECATED: Use src.providers.extract_usage(chunk, model) instead.
    """
    try:
        text = chunk.decode("utf-8", errors="ignore")
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("data: ") and line != "data: [DONE]":
                data = json.loads(line[6:])
                usage = data.get("usage", {})
                if usage:
                    return usage
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return {}


def _extract_usage_from_response(resp_data: dict) -> dict:
    """Extract token usage from a non-streaming response body.

    Handles multiple provider formats:
    - OpenAI: {"usage": {"prompt_tokens": N, "completion_tokens": N, "total_tokens": N}}
    - Anthropic: {"usage": {"input_tokens": N, "output_tokens": N}}
    - Google: {"usageMetadata": {"promptTokenCount": N, "candidatesTokenCount": N}}

    Returns: {"input_tokens": N, "output_tokens": N, "total_tokens": N}
    """
    # Google format
    usage_meta = resp_data.get("usageMetadata")
    if usage_meta:
        input_tokens = int(usage_meta.get("promptTokenCount", 0))
        output_tokens = int(usage_meta.get("candidatesTokenCount", 0))
        total = int(usage_meta.get("totalTokenCount", input_tokens + output_tokens))
        if input_tokens or output_tokens:
            return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total}

    # OpenAI/Anthropic format
    usage = resp_data.get("usage", {})
    if usage:
        input_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0))
        output_tokens = usage.get("completion_tokens", usage.get("output_tokens", 0))
        total_tokens = usage.get("total_tokens", input_tokens + output_tokens)
        if input_tokens or output_tokens:
            return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total_tokens}

    return {}

@app.post("/v1/chat/completions")
async def llm_proxy(
    request: Request,
    x_resgov_agent_id: Optional[str] = Header(None, alias="X-ResGov-Agent-ID"),
    owner=Depends(require_api_key),
):
    """
    OpenAI-compatible LLM proxy with budget governance.

    Usage:
        Set base_url to http://localhost:8080/v1
        Add header: X-ResGov-Agent-ID: your-agent-id

    Flow:
        1. Reserve budget (pessimistic max_cost estimate)
        2. Forward request to upstream LLM provider
        3. Stream response back to client
        4. Finalize budget with actual token usage
    """
    if not x_resgov_agent_id:
        raise HTTPException(
            status_code=400,
            detail="Missing X-ResGov-Agent-ID header. Set your agent ID to enable budget tracking.",
        )

    # Parse request body
    body = await request.json()
    model = body.get("model", "default")
    max_tokens = body.get("max_tokens", 2048)
    is_stream = body.get("stream", False)

    # Calculate max cost for reservation
    price_table = _get_price_table()
    max_cost = _estimate_max_cost(model, max_tokens, price_table, messages=body.get("messages", []))

    # Phase 1: Reserve budget (milliseconds lock)
    engine = BudgetEngine(rgf_config=RGF_CONFIG)
    try:
        reservation = engine.reserve_budget(x_resgov_agent_id, max_cost, model=model, max_tokens=max_tokens)
    except Exception as e:
        logger.error(f"Budget reservation failed: {e}")
        fail_safe_action = RGF_CONFIG.get("global", {}).get("fail_safe_action", "deny")
        if fail_safe_action == "allow":
            logger.warning(f"Budget system offline (fail_safe_action=allow). Allowing request for {x_resgov_agent_id}")
            # Bypass budget, proceed with upstream call
            class DummyReservation:
                status = "reserved"
                reserved_cost = max_cost # Still track for potential later finalization
            reservation = DummyReservation()
        else: # default to deny
            raise HTTPException(
                status_code=500,
                detail=f"Budget system temporarily unavailable. ({e})"
            )

    if reservation["status"] == "denied":
        _metrics["bookings_denied_total"] += 1
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "type": "budget_exceeded",
                    "message": reservation["message"],
                    "agent_id": x_resgov_agent_id,
                    "reason": reservation["reason"],
                }
            },
        )

    reserved_cost = reservation["reserved_cost"]

    # Phase 2: Forward to upstream provider
    provider = os.environ.get("RESGOV_PROVIDER", "openrouter")

    if provider == "github-copilot":
        upstream_url = "https://api.githubcopilot.com/chat/completions"
        upstream_key = os.environ.get("GITHUB_COPILOT_TOKEN", "")
        if not upstream_key:
            raise HTTPException(
                status_code=500,
                detail="GITHUB_COPILOT_TOKEN not configured. Set your GitHub OAuth token.",
            )
        headers = {
            "Authorization": f"Bearer {upstream_key}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2026-03-10",
            "Copilot-Integration-Id": "vscode-chat",
        }
    else:
        upstream_url = os.environ.get("RESGOV_UPSTREAM_URL", "https://openrouter.ai/api/v1/chat/completions")
        upstream_key = os.environ.get("RESGOV_UPSTREAM_API_KEY", "")
        if not upstream_key:
            raise HTTPException(
                status_code=500,
                detail="RESGOV_UPSTREAM_API_KEY not configured. Set your OpenRouter/AI provider API key.",
            )
        headers = {
            "Authorization": f"Bearer {upstream_key}",
            "Content-Type": "application/json",
        }

    if is_stream:
        # Streaming: forward chunks, track usage, finalize after stream
        actual_input_tokens = 0
        actual_output_tokens = 0

        async def stream_with_finalization():
            nonlocal actual_input_tokens, actual_output_tokens
            try:
                async with _httpx_client.stream("POST", upstream_url, json=body, headers=headers) as resp:
                    async for chunk in resp.aiter_bytes():
                        # Provider-specific usage extraction
                        from .providers import extract_usage as _provider_extract_usage
                        usage = _provider_extract_usage(chunk, model)
                        if usage:
                            actual_input_tokens = usage.get("input_tokens", actual_input_tokens)
                            actual_output_tokens = usage.get("output_tokens", actual_output_tokens)
                        yield chunk
            finally:
                # Phase 3: Finalize budget
                # Streaming backends rarely send usage in chunks — fallback to estimation
                pricing = price_table.get(model, price_table["default"])
                if not actual_input_tokens and not actual_output_tokens:
                    # Fallback: estimate from messages + max_tokens
                    actual_input_tokens = _estimate_input_tokens(body.get("messages", []))
                    actual_output_tokens = max_tokens
                input_cost = round(actual_input_tokens * pricing.get("input", 0.000001), 6)
                output_cost = round(actual_output_tokens * pricing.get("output", 0.000003), 6)
                actual_cost = round(input_cost + output_cost, 6)
                # finalize is fire-and-forget — never let it break the response
                try:
                    engine.finalize_budget(x_resgov_agent_id, reserved_cost, actual_cost)
                except Exception as finalize_err:
                    logger.error(f"finalize_budget failed after stream: {finalize_err}")

        return StreamingResponse(
            stream_with_finalization(),
            media_type="text/event-stream",
            headers={
                "X-ResGov-Agent-ID": x_resgov_agent_id,
                "X-ResGov-Reserved": str(reserved_cost),
            },
        )
    else:
        # Non-streaming: simple forward + finalize
        try:
            resp = await _httpx_client.post(upstream_url, json=body, headers=headers)
            resp_data = resp.json()

            # Extract usage — handles OpenAI, Anthropic, Google formats
            usage = _extract_usage_from_response(resp_data)
            pricing = price_table.get(model, price_table["default"])

            input_tokens = usage.get("input_tokens") or _estimate_input_tokens(body.get("messages", []))
            output_tokens = usage.get("output_tokens") or max_tokens

            input_cost = round(input_tokens * pricing.get("input", 0.000001), 6)
            output_cost = round(output_tokens * pricing.get("output", 0.000003), 6)
            actual_cost = round(input_cost + output_cost, 6)

            # Phase 3: Finalize
            engine.finalize_budget(x_resgov_agent_id, reserved_cost, actual_cost)

            # Inject cost info into response for transparency
            resp_data["resgov_cost"] = {
                "estimated": reserved_cost,
                "actual": actual_cost,
                "refund": round(reserved_cost - actual_cost, 6),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }

            return JSONResponse(content=resp_data)
        except Exception as e:
            # Refund on error — finalize is fire-and-forget, never block the 502 response
            try:
                engine.finalize_budget(x_resgov_agent_id, reserved_cost, 0)
            except Exception as finalize_err:
                logger.error(f"finalize_budget failed during error refund: {finalize_err}")
            raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")

# --- Dashboard (Basic Auth) ---

DASH_USER = os.environ.get("RESGOV_DASH_USER", "admin")
DASH_PASS = os.environ.get("RESGOV_DASH_PASS", "")


async def require_dashboard_auth(request: Request):
    """Require Basic Auth for dashboard if DASH_PASS is set."""
    import base64
    dash_pass = os.environ.get("RESGOV_DASH_PASS", "")
    dash_user = os.environ.get("RESGOV_DASH_USER", "admin")
    if not dash_pass:
        return  # No auth required if not configured
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        raise HTTPException(status_code=401, detail="Authentication required", headers={"WWW-Authenticate": "Basic"})
    try:
        decoded = base64.b64decode(auth[6:]).decode()
        username, password = decoded.split(":", 1)
        if not (secrets.compare_digest(username, dash_user) and secrets.compare_digest(password, dash_pass)):
            raise HTTPException(status_code=401, detail="Invalid credentials")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authorization header")


# --- Dashboard API ---

@app.get("/dash/api/stats")
async def dash_stats(request: Request):
    """Aggregated statistics for the dashboard."""
    await require_dashboard_auth(request)
    engine = BudgetEngine(rgf_config=RGF_CONFIG)
    from .middleware import get_db
    db = get_db()

    # Agent counts
    total_agents = db.execute("SELECT COUNT(*) as cnt FROM agents WHERE status != 'revoked'").fetchone()["cnt"]
    active_agents = db.execute("SELECT COUNT(DISTINCT agent_id) as cnt FROM bookings WHERE created_at > datetime('now', '-1 day')").fetchone()["cnt"]

    # Booking stats
    total_bookings = db.execute("SELECT COUNT(*) as cnt FROM bookings").fetchone()["cnt"]
    denied_bookings = db.execute("SELECT COUNT(*) as cnt FROM bookings WHERE status = 'denied'").fetchone()["cnt"]

    # Cost totals
    total_spent = db.execute("SELECT COALESCE(SUM(cost), 0) as total FROM bookings WHERE status IN ('completed', 'success')").fetchone()["total"]
    total_reserved = db.execute("SELECT COALESCE(SUM(estimated_cost), 0) as total FROM bookings WHERE status IN ('completed', 'success')").fetchone()["total"]

    # Recent denials (last 24h)
    recent_denials = db.execute("SELECT COUNT(*) as cnt FROM bookings WHERE status = 'denied' AND created_at > datetime('now', '-1 day')").fetchone()["cnt"]

    return {
        "agents": {"total": total_agents, "active_24h": active_agents},
        "bookings": {"total": total_bookings, "denied": denied_bookings, "denied_24h": recent_denials},
        "costs": {
            "total_spent": round(total_spent, 4),
            "total_reserved": round(total_reserved, 4),
            "total_refunded": round(total_reserved - total_spent, 4),
        },
        "metrics": _metrics,
    }


@app.get("/dash/api/agents")
async def dash_agents(request: Request):
    """List all agents with budget status for the dashboard."""
    await require_dashboard_auth(request)
    from .middleware import get_db
    db = get_db()

    agents = db.execute("SELECT * FROM agents WHERE status != 'revoked'").fetchall()
    result = []
    for agent in agents:
        budgets = db.execute("SELECT * FROM budgets WHERE agent_id = ?", (agent["id"],)).fetchall()
        daily = next((b for b in budgets if b["period"] == "daily"), None)
        monthly = next((b for b in budgets if b["period"] == "monthly"), None)
        usage = db.execute(
            "SELECT COALESCE(SUM(cost), 0) as total FROM bookings WHERE agent_id = ? AND status = 'success'",
            (agent["id"],)
        ).fetchone()

        agent_data = {
            "agent_id": agent["id"],
            "name": agent["name"],
            "org_id": agent["org_id"] if agent["org_id"] else "default",
            "daily_limit": daily["limit_amount"] if daily else 0,
            "daily_remaining": round(daily["limit_amount"] - daily["spent_amount"], 4) if daily else 0,
            "monthly_limit": monthly["limit_amount"] if monthly else 0,
            "monthly_remaining": round(monthly["limit_amount"] - monthly["spent_amount"], 4) if monthly else 0,
            "total_spent": round(usage["total"], 4) if usage else 0,
            "status": agent["status"] if agent["status"] else "active",
        }
        result.append(agent_data)
    return result


@app.get("/dash/api/bookings")
async def dash_bookings(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status_filter: Optional[str] = Query(default=None, alias="status"),
):
    """Recent bookings for the dashboard."""
    await require_dashboard_auth(request)
    from .middleware import get_db
    db = get_db()

    query = "SELECT * FROM bookings"
    params = []
    if status_filter:
        query += " WHERE status = ?"
        params.append(status_filter)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]

@app.get("/dash", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the monitoring dashboard."""
    await require_dashboard_auth(request)
    dash_path = os.path.join(os.path.dirname(__file__), "..", "dash", "index.html")
    if os.path.exists(dash_path):
        with open(dash_path) as f:
            return f.read()
    return "<h1>ResGov Dashboard</h1><p>Dashboard not built yet.</p>"
