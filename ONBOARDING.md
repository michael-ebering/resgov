# ResGov (RGF) — Developer Onboarding

> Get a local ResGov instance running in under 5 minutes.

## Prerequisites

- Python 3.12+
- Git
- Docker & Docker Compose (for containerized setup)
- An OpenRouter API key (for LLM proxy testing)

## Quick Start (One-Line Installer)

```bash
curl -fsSL https://raw.githubusercontent.com/michael-ebering/resgov/main/install.sh | bash
```

This clones the repo, creates `.env`, generates an admin token, and starts the container.

## Quick Start (Local Dev, No Docker)

```bash
git clone https://github.com/michael-ebering/resgov.git
cd resgov
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set at minimum:

```bash
RESGOV_ADMIN_TOKEN=your-admin-token-here
RESGOV_API_KEYS=demo-key:dev-user
```

Start the server:

```bash
uvicorn src.main:app --reload --port 8080
```

Verify:

```bash
curl http://localhost:8080/health
# → {"status":"ok","version":"0.4.4"}
```

Interactive API docs: http://localhost:8080/docs

## Quick Start (Docker)

```bash
git clone https://github.com/michael-ebering/resgov.git
cd resgov
cp .env.example .env
# Edit .env → set RESGOV_ADMIN_TOKEN
docker compose up -d
```

Services:
- **Core Proxy API:** http://localhost:8080/v1
- **Dashboard:** http://localhost:8080/dash
- **API Docs (Swagger):** http://localhost:8080/docs
- **Health V2:** http://localhost:8080/health

## Project Structure

```
resgov/
├── src/
│   ├── main.py          # FastAPI app factory, lifespan, router registration
│   ├── api.py           # All API route definitions
│   ├── engine.py        # BudgetEngine: reserve, finalize, predict
│   ├── config.py        # .rgf file parser (TOML)
│   ├── auth.py          # API key + admin token verification
│   ├── models.py        # Pydantic request/response models
│   ├── middleware.py     # CORS, request logging
│   ├── providers.py     # LLM provider adapters (OpenRouter, etc.)
│   ├── price_cache.py   # Token price caching
│   ├── scheduler.py     # Background tasks (budget resets, decay)
│   └── leadcollector.py # Lead collection sub-app
├── tests/               # Pytest test suite
├── dash/                # Dashboard static files (HTML/JS)
├── docs/                # Additional documentation
├── docker-compose.yml
├── Dockerfile
├── Dockerfile.lead
├── requirements.txt
├── .env.example
└── .rgf                 # Your local governance rules (gitignored)
```

## Running Tests

```bash
# All tests
pytest tests/ -v

# Specific module
pytest tests/test_engine.py -v

# With parallel execution (requires pytest-xdist)
pip install pytest-xdist
pytest tests/ -n 4 --dist loadfile
```

**Test conventions:**
- Tests use an isolated in-memory SQLite DB per test file
- `conftest.py` at root level provides shared fixtures
- `--dist loadfile` ensures file-level isolation with xdist

## Creating Your First `.rgf` File

Create a `.rgf` file in the project root:

```toml
[global]
currency = "USD"
fail_safe_action = "deny"

[agents.my-agent]
daily_budget = 5.00
max_tokens_per_request = 8192
allowed_models = ["anthropic/claude-sonnet-4", "openrouter/deepseek/deepseek-v4-flash"]
allowed_tools = ["web_search", "web_scraper"]
```

Start ResGov with the `.rgf` loaded:

```bash
# The engine auto-detects .rgf in the working directory
uvicorn src.main:app --reload --port 8080
```

Test the governance:

```bash
# Generate an API key via admin endpoint
curl -X POST http://localhost:8080/api/v1/admin/generate-key \
  -H "X-Admin-Token: your-admin-token" \
  -H "Content-Type: application/json" \
  -d '{"owner": "dev-user", "agent_id": "my-agent"}'

# Use the proxy (replace <KEY> with the generated key)
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer <KEY>" \
  -H "X-ResGov-Agent-ID: my-agent" \
  -H "Content-Type: application/json" \
  -d '{"model": "anthropic/claude-sonnet-4", "messages": [{"role": "user", "content": "Hello"}]}'
```

## Key API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | None | Health check |
| `/docs` | GET | None | Swagger UI |
| `/v1/chat/completions` | POST | API Key | LLM proxy (OpenAI-compatible) |
| `/api/v1/book` | POST | API Key | Book non-LLM resources |
| `/api/v1/usage/{agent_id}` | GET | API Key | Get agent usage stats |
| `/api/v1/agents/{id}/prediction` | GET | API Key | Budget forecast |
| `/api/v1/admin/generate-key` | POST | Admin Token | Create new API key |
| `/api/v1/admin/reset-daily` | POST | Admin Token | Reset daily budgets |
| `/api/v1/audit` | GET | Admin Token | Audit trail |
| `/metrics` | GET | None | Prometheus metrics |

## Debugging Tips

**Server won't start:**
- Check `.env` exists and has `RESGOV_ADMIN_TOKEN` set
- Port 8080 already in use? → `lsof -i :8080`
- Missing deps? → `pip install -r requirements.txt`

**Budget not enforced:**
- Ensure `.rgf` file is in the working directory (not project root if CWD differs)
- Check that `agent_id` in the request header matches the `.rgf` section
- Verify `fail_safe_action` — `deny` blocks on proxy failure, `allow` passes through

**Tests fail with DB errors:**
- Run without xdist first: `pytest tests/ -v` (no `-n` flag)
- Check for stale `resgov.db` in the working directory
- Each test file should use its own conftest with in-memory DB

**Proxy returns 403 budget exceeded:**
- Reset daily budgets: `curl -X POST http://localhost:8080/api/v1/admin/reset-daily -H "X-Admin-Token: your-token"`
- Increase `daily_budget` in `.rgf`
- Check usage: `curl http://localhost:8080/api/v1/usage/my-agent -H "Authorization: Bearer <KEY>"`

## Common Workflows

### Adding a New API Endpoint

1. Define Pydantic models in `src/models.py`
2. Add route in `src/api.py`
3. Add business logic in `src/engine.py` if needed
4. Write tests in `tests/`
5. Run `pytest tests/ -v`

### Adding a New LLM Provider

1. Add provider adapter in `src/providers.py`
2. Update `src/config.py` if provider needs special config
3. Add price data to `src/price_cache.py`
4. Test with a real `.rgf` config allowing the new model

## Resources

- [README.md](README.md) — Full feature documentation & architecture
- [CONTRIBUTING.md](CONTRIBUTING.md) — Code style & PR process
- [CHANGELOG.md](CHANGELOG.md) — Version history
- [DEPLOYMENT.md](DEPLOYMENT.md) — Production deployment (Traefik, HTTPS, backups, monitoring)
- [docs/adr.md](docs/adr.md) — Architecture Decision Records
- [docs/rgf-examples.md](docs/rgf-examples.md) — `.rgf` configuration examples
- [API Docs (Swagger)](http://localhost:8080/docs) · [Live API Docs](https://api.resgov.silentops.cloud/docs) — Interactive endpoint reference
- [Hermes Agent Docs](https://hermes-agent.nousresearch.com/docs) — If using ResGov as a Hermes proxy
