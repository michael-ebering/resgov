<div align="center">

<img src="https://img.shields.io/badge/Python-3.12+-blue?logo=python&logoColor=white" alt="Python">
<img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white" alt="FastAPI">
<img src="https://img.shields.io/badge/SQLite-WAL_Mode-003B57?logo=sqlite&logoColor=white" alt="SQLite">
<img src="https://img.shields.io/badge/Docker-✓-2496ED?logo=docker&logoColor=white" alt="Docker">
<img src="https://img.shields.io/badge/Tests-44/44_passing-success" alt="Tests">
<img src="https://img.shields.io/badge/License-BSL_1.1-orange" alt="License">
<a href="https://github.com/michael-ebering/resgov/stargazers"><img src="https://img.shields.io/github/stars/michael-ebering/resgov?style=social" alt="Stars"></a>

# **ResGov**

### Resource Governance Framework (RGF) for Multi-Agent Environments

**The missing layer between your agents and your budget.**
_STOP letting AI agents burn through your API keys in an uncontrolled manner._

ResGov is the Resource Governance Framework (RGF) for Multi-Agent environments — a lightweight proxy layer between your agents and your API budget. It complements MCP and A2A to prevent cost explosion through real-time quota enforcement, per-agent budget tracking, and streaming cost governance.

📡 [Live Demo](https://resgov.silentops.cloud) · [Quick Start](#-quick-start) · [Architecture](#-architecture) · [API](#-api-reference)

</div>

---

## ☝️ Why ResGov (RGF) Exists

### The Problem
Your agents make thousands of API calls per day. But nobody knows:
- **How much** each agent costs
- **Who** triggered that unexpected $47 OpenRouter bill
- **When** quotas were exceeded
- **Why** something failed

### The Landscape
- **MCP** → Defines _how agents talk_ to tools
- **A2A** → Defines _how agents delegate_ to each other
- **RGF (ResGov)** → Defines _how agents **share finite resources**_

That last piece? Doesn't exist. Until now.

### The Numbers
> 57% of companies run agents in production (G2 2026).
> Multi-agent market: $7.8B → $52.6B by 2030.
> **Zero** open-source tools for cross-agent resource governance.

---

## ☝️ Features

### Implemented

| Feature | Status |
|:---|:---:|
| **LLM Proxy** (OpenAI/Anthropic compatible, streaming) | ✅ |
| **Pre-Commit / Finalize Budget Pattern** (no double-spend) | ✅ |
| **Per-Agent Budgets** (daily / monthly / total) | ✅ |
| **Real-Time Cost Tracking** | ✅ |
| **Quota Enforcement** (hard deny with reason) | ✅ |
| **Audit Trail** (every request logged, paginated) | ✅ |
| **Multi-Tenant** (organizations, team isolation) | ✅ |
| **Row-Level Locking** (concurrency-safe) | ✅ |
| **Webhook Notifications** (HMAC-SHA256, budget exceeded, agent revoked) | ✅ |
| **API Key Management** (DB-backed, CRUD, revoke, expiry) | ✅ |
| **Rate Limiting** (60 req/min per IP) | ✅ |
| **Prometheus Metrics** (`/metrics`) | ✅ |
| **Dark-Mode Dashboard** (auth-protected) | ✅ |
| **Soft-Delete Agents** (keep historical data) | ✅ |
| **Graceful Shutdown** (Docker / K8s ready) | ✅ |
| **LangChain / CrewAI** integration examples | ✅ |
| **Auto Budget Reset** (daily/monthly scheduler) | ✅ |
| **Crash Recovery** (auto-finalize expired reservations) | ✅ |
| **WAL Backup Script** (automated SQLite backups) | ✅ |
| **Health Endpoint v2** (DB + scheduler status) | ✅ |

### Planned

| Feature | ETA |
|:---|:---:|
| **Redis Backend** (multi-instance scaling) | v0.5 |
| **Slack / Discord Alert Templates** | v0.5 |
| **Terraform Provider** | v0.6 |
| **Policy Engine** (OPA integration) | v0.6 |

---

## ☝️ Quick Start

### Docker (recommended)
```bash
git clone https://github.com/michael-ebering/resgov.git
cd resgov
cp .env.example .env          # Set RESGOV_ADMIN_TOKEN
docker compose up -d
# API:       http://localhost:8080
# Proxy:     http://localhost:8080/v1
# Dashboard: http://localhost:8080/dash
# Health:    http://localhost:8080/health
```

### Self-Hosted (bare metal)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
RESGOV_DB_PATH=./resgov.db python -m uvicorn src.api:app --host 0.0.0.0 --port 8080
```

### Production with Traefik + SSL
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

---

## ☝️ LLM Proxy (the killer feature)

ResGov (RGF) acts as a **transparent OpenAI/Anthropic-compatible proxy**. Your agents don't need custom code — just change the `base_url`.

### How it works
```
Agent → RGF Proxy → Budget Check → Upstream LLM (OpenRouter, etc.)
                        ↓
                   1. RESERVE pessimistic max_cost (milliseconds lock)
                   2. STREAM response to agent (no DB lock!)
                   3. FINALIZE with actual token usage (refund difference)
```

**Key insight:** The database lock lasts only milliseconds (BEGIN IMMEDIATE + UPDATE + COMMIT). The streaming phase is completely lock-free. No deadlocks, no blocked parallel agents.

### Framework Integration

#### LangChain
```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="anthropic/claude-sonnet-4",
    base_url="http://localhost:8080/v1",
    api_key="your-rgf-api-key",
    default_headers={"X-ResGov-Agent-ID": "my-agent-01"},
)

response = llm.invoke("Analyze this data...")
```

#### CrewAI
```python
from crewai import Agent, LLM

llm = LLM(
    model="openai/anthropic/claude-sonnet-4",
    base_url="http://localhost:8080/v1",
    api_key="your-rgf-api-key",
    extra_headers={"X-ResGov-Agent-ID": "crew-lead"},
)

agent = Agent(
    role="Researcher",
    llm=llm,
    goal="Find insights...",
)
```

#### OpenAI SDK (direct)
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="your-rgf-api-key",
)

response = client.chat.completions.create(
    model="anthropic/claude-sonnet-4",
    messages=[{"role": "user", "content": "Hello"}],
    extra_headers={"X-ResGov-Agent-ID": "my-agent"},
    stream=True,  # Fully supported
)
```

#### Raw curl
```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer your-rgf-api-key" \
  -H "X-ResGov-Agent-ID: my-agent" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "anthropic/claude-sonnet-4",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 1024,
    "stream": true
  }'
```

### Budget Denied Response
When an agent exceeds its budget, the proxy returns immediately (no upstream call):
```json
{
  "error": {
    "type": "budget_exceeded",
    "message": "Daily budget exceeded. Limit: $5.00, Spent: $4.95, Remaining: $0.05, Required: $0.25",
    "agent_id": "my-agent",
    "reason": "daily_budget_exceeded"
  }
}
```
HTTP 403. Zero upstream costs.

---

## ☝️ Governance API

For non-LLM resources (web scraping, file operations, third-party APIs):

```http
# Register an agent
POST /api/v1/agents
{
    "agent_id": "scraper-01",
    "name": "Web Scraper",
    "org_id": "team-alpha",
    "daily_limit": 5.00,
    "monthly_limit": 100.00
}

# Book a resource
POST /api/v1/book
{
    "agent_id": "scraper-01",
    "resource_type": "api_call",
    "action": "pexels_search",
    "cost": 0.05,
    "metadata": {"query": "nature", "count": 10}
}

# Get agent status
GET /api/v1/agents/scraper-01

# Usage history
GET /api/v1/usage/scraper-01?limit=50

# Update budget
PUT /api/v1/agents/scraper-01/budget
{"period": "daily", "limit_amount": 10.00}

# List all active agents
GET /api/v1/agents

# Soft-delete an agent
DELETE /api/v1/agents/scraper-01
```

### Admin Endpoints (require `X-Admin-Token` header)
```http
POST /api/v1/admin/reset-daily     → Reset all daily budgets
POST /api/v1/admin/reset-monthly   → Reset all monthly budgets
POST /api/v1/admin/generate-key    → Generate new API key
GET  /api/v1/admin/keys            → List all API keys
DELETE /api/v1/admin/keys/{id}     → Revoke an API key
GET  /api/v1/audit?page=1&page_size=100  → Paginated audit trail
GET  /metrics                      → Prometheus metrics
```

---

## ☝️ Architecture

```
                    ┌──────────────────────────────────┐
                    │          RGF Broker              │
                    └──────────────┬───────────────────┘
                                   │
            ┌──────────┬───────────┼───────────┬──────────────┐
            │          │           │           │              │
     ┌──────▼────┐ ┌───▼───┐ ┌────▼────┐ ┌───▼─────┐ ┌─────▼──────┐
     │   Auth    │ │Budget │ │  LLM    │ │Webhooks │ │ Prometheus │
     │   Layer   │ │Engine │ │  Proxy  │ │Discord/ │ │  /metrics  │
     │ API Keys  │ │       │ │Reserve  │ │Slack    │ │            │
     │ Admin Tok │ │       │ │Stream   │ │HMAC     │ │            │
     └───────────┘ └───┬───┘ │Finalize │ └─────────┘ └────────────┘
                       │     └─────────┘
                ┌──────▼──────────────┐
                │    SQLite (WAL)     │
                │  ┌──────┬────────┐  │
                │  │Agents│Budgets │  │
                │  └──────┴────────┘  │
                │  ┌────────────────┐ │
                │  │Bookings (Audit)│ │
                │  └────────────────┘ │
                │  ┌────────────────┐ │
                │  │  Reserved      │ │
                │  │  Budgets       │ │
                │  └────────────────┘ │
                └─────────────────────┘
```

### Design Decisions

- **SQLite WAL**: Concurrent reads + serialized writes. No separate DB server. Perfect for single-instance and edge deployments.
- **Pre-Commit / Finalize Pattern**: Reserve pessimistic max_cost at stream start (milliseconds lock), refund difference at stream end. No long-held locks.
- **Thread-Local Connections**: No connection pool headaches. One connection per thread, properly isolated.
- **Webhooks**: Fire-and-forget async with HMAC-SHA256 signatures. Your agents don't wait for Slack to render.
- **Price Table**: Configurable via `RESGOV_PRICE_TABLE` env var. Ships with defaults for GPT-4o, Claude Sonnet, DeepSeek, Gemini.
- **Auto Scheduler**: Daily budget reset at 00:00 UTC, monthly on 1st, expired reservation cleanup every 2 minutes.
- **Crash Recovery**: Reserved budgets auto-expire after 5 minutes. No stuck reservations after agent crashes.

---

## ☝️ Dashboard

Dark-mode real-time monitoring at `http://localhost:8080/dash` (auth-protected via `RESGOV_DASH_USER` / `RESGOV_DASH_PASS`):

- Live agent status (active / paused / revoked)
- Budget consumption bars (green → yellow → red)
- Recent bookings table
- Denied requests counter
- Last refresh timestamp

---

## ☝️ Production Checklist

| Concern | Solution |
|---|---|
| **Authentication** | DB-backed API keys via `X-API-Key` header + Admin token |
| **Rate Limiting** | 60 requests/minute per IP |
| **CORS** | Configurable allowed origins |
| **TLS/SSL** | Traefik with Let's Encrypt |
| **Health Checks** | `/health` endpoint (DB + scheduler status) + Docker HEALTHCHECK |
| **Graceful Shutdown** | SIGTERM handling, connection cleanup, scheduler stop |
| **Thread Safety** | Thread-local SQLite connections |
| **Concurrency** | WAL mode + BEGIN IMMEDIATE + retry |
| **Budget Safety** | Pre-commit / finalize, no double-spend |
| **Crash Recovery** | Auto-finalize expired reservations (5-min timeout) |
| **Backups** | WAL backup script with configurable retention |

---

## ☝️ Development

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run tests
pytest tests/ -v

# Run locally
python -m uvicorn src.api:app --reload --port 8080

# Build Docker
docker build -t resgov:latest .
```

### Test Coverage
```
tests/test_evals.py — 44/44 passing
  Budget enforcement, concurrent access, budget reset,
  parallel stress, invalid agents, invalid budgets,
  empty state, audit trail, pagination,
  auth, API key CRUD, soft-delete,
  proxy reserve/finalize, crash recovery,
  admin endpoints, health endpoint
```

---

## ☝️ Roadmap

### v0.5 (next)
- [ ] Redis backend for multi-instance deployments
- [ ] Slack / Discord webhook templates
- [ ] Budget forecasting (spend pattern analysis)
- [ ] Per-resource-type budgets (separate limits for `api_call` vs `compute`)

### v0.6
- [ ] OPA (Open Policy Engine) integration
- [ ] Terraform provider
- [ ] Helm chart for Kubernetes

### v1.0
- [ ] Cloud SaaS offering (resgov.silentops.cloud)
- [ ] Team management UI
- [ ] SSO / SAML
- [ ] Historical analytics (30/60/90 day spend reports)

---

## ☝️ Contributing

1. Fork
2. Create feature branch (`git checkout -b feature/amazing`)
3. Run tests (`pytest tests/ -v`)
4. Commit (`git commit -m "feat: add amazing thing"`)
5. Push (`git push origin feature/amazing`)
6. Open Pull Request

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for code standards.

---

## ☝️ License

**BSL 1.1 (Business Source License)**

- ✅ Free for personal use, internal use, and non-commercial use
- ✅ Free for companies with < $1M ARR
- ❌ Cannot offer a competing commercial service using this code
- 🔄 Automatically converts to Apache 2.0 on **January 1, 2029**

See [LICENSE](LICENSE) for full text.

---

<div align="center">

<sub>Built by [SilentOps](https://silentops.cloud) with focus on correctness, speed, and real-world impact.</sub>

⭐ Star this repo if it saved your API budget.

</div>
