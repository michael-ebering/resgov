# Architecture Decision Records (ADRs)

> Key architectural decisions and their rationale.

## ADR-001: SQLite WAL Mode Instead of PostgreSQL

**Status:** Accepted  
**Date:** 2026-05-29

### Context

ResGov needs a persistent store for budget tracking, API keys, and audit logs. We evaluated PostgreSQL, MySQL, and SQLite.

### Decision

Use SQLite in WAL (Write-Ahead Logging) mode as the default storage backend.

### Rationale

- **Zero-config deployment:** No separate database service to manage, monitor, or back up. `pip install` and go.
- **Sufficient performance:** For the target use case (single-instance proxy serving one organization), SQLite handles thousands of concurrent reads with serialized writes. WAL mode allows concurrent readers without blocking.
- **File-based backup:** A single `.cp` or `.backup` command creates a consistent snapshot. No `pg_dump` needed.
- **Edge-friendly:** Runs on resource-constrained infrastructure (IoT, edge servers, CI runners) where PostgreSQL is overkill.
- **Migration path:** The storage layer is abstracted behind the `BudgetEngine` interface. A Redis/Dragonfly or PostgreSQL backend can be added later (see Roadmap v0.5).

### Constraints

- Not suitable for horizontal multi-instance deployments. The WAL file is local to one process.
- Write throughput is limited to one writer at a time (serialized writes in WAL mode).

### Alternatives Considered

| Option | Rejected Because |
|--------|------------------|
| PostgreSQL | Operational overhead disproportionate for single-instance use case |
| Redis | Volatile by default; persistence adds complexity |
| MongoDB | Document model doesn't match the relational budget/agent structure |
| In-memory only | No crash recovery; budgets lost on restart |

---

## ADR-002: Pessimistic Locking for Budget Reservation

**Status:** Accepted  
**Date:** 2026-05-29

### Context

Multiple agents may make concurrent API calls through ResGov. Each call's cost must be deducted from the remaining budget atomically. Two concurrent requests must not both succeed based on stale budget reads (double-spending).

### Decision

Use a pessimistic pre-commit pattern:

1. At stream **start**: acquire a DB lock, read current spend, calculate pessimistic `max_cost`, reserve it atomically, release lock.
2. During stream: no lock held (the expensive network I/O phase).
3. At stream **end**: acquire lock, read actual token usage, refund the difference between reserved and actual, release lock.

### Rationale

- **Prevents double-spending:** The lock ensures that two concurrent requests never both read the same remaining budget.
- **Lock-free streaming:** The lock is held for microseconds (a single DB write), not during the entire LLM response stream. This is critical because LLM streams last seconds to minutes.
- **Pessimistic over optimistic:** We chose pessimistic locking (reserve worst-case upfront) over optimistic concurrency control (retry on conflict) because:
  - Retries are wasteful: an agent has already waited for the LLM response before being told "budget exceeded."
  - The lock hold time is negligible (microseconds), so contention is minimal.

### Crash Recovery

If the ResGov process crashes after reservation but before finalize, the reserved amount is "stuck." A background job (every 5 minutes) scans for reservations older than the expected maximum stream duration and refunds them.

### Alternatives Considered

| Option | Rejected Because |
|--------|------------------|
| Optimistic concurrency (retry) | Wasteful: LLM response already streamed before rejection |
| Row-level advisory locks | SQLite doesn't support advisory locks |
| Redis-based distributed lock | Adds Redis dependency; unnecessary for single instance |

---

## ADR-003: `.rgf` File Format (TOML)

**Status:** Accepted  
**Date:** 2026-05-29

### Context

Governance rules (budgets, model allowlists, tool restrictions) need a human-readable, VCS-friendly configuration format.

### Decision

Use TOML, governed by a `.rgf` file (analogous to `.gitignore`, `.env`, `.editorconfig`).

### Rationale

- **Human-readable:** Lower cognitive overhead than YAML/JSON for non-developers.
- **Trivially parseable:** Python's `tomllib` (stdlib since 3.11) handles it with zero dependencies.
- **Familiar convention:** The `.rgf` extension signals "this is a governance rules file" and is auto-detected by ResGov from the working directory.
- **Section-per-agent:** TOML's `[table]` syntax maps naturally to per-agent configuration.

### Constraints

- Only one `.rgf` file per ResGov instance (no includes/imports).
- For multi-instance setups, manage `.rgf` files per deployment (Ansible, Terraform, etc.).

### Alternatives Considered

| Option | Rejected Because |
|--------|------------------|
| YAML | Indentation errors, larger spec, needs PyYAML dependency |
| JSON | No comments, painful for multi-line lists |
| Environment variables | Doesn't scale to per-agent sections |
| Database config | Circular dependency — DB needs auth, auth needs config |

---

## ADR-004: LLM Proxy Passthrough Pattern

**Status:** Accepted  
**Date:** 2026-05-29

### Context

ResGov's core function is a transparent LLM proxy. It must work with existing frameworks (CrewAI, LangLang, LlamaIndex, custom code) without SDK changes.

### Decision

Implement an OpenAI-compatible `/v1/chat/completions` endpoint. Frameworks switch by changing `base_url` only.

### Rationale

- **Zero-friction adoption:** Every major LLM framework supports configuring a custom `base_url`.
- **No vendor lock-in:** If a user outgrows ResGov, they revert the `base_url` — no code changes.
- **Header-based routing:** Agent ID and org ID are passed via HTTP headers (`X-ResGov-Agent-ID`), keeping the request body untouched.

### Supported Providers

| Provider | Base URL | Auth |
|----------|----------|------|
| OpenRouter | `https://openrouter.ai/api/v1` | API Key |
| GitHub Copilot | `https://api.githubcopilot.com` | OAuth Token |
| Custom OpenAI-compatible | Configurable | API Key |

Each provider adapter handles model name mapping, auth headers, and response normalization.

---

## ADR-005: Modular Provider Architecture

**Status:** Accepted  
**Date:** 2026-05-29

### Context

ResGov must support multiple LLM providers (OpenRouter, GitHub Copilot, potentially direct OpenAI/Anthropic) with different auth methods, model naming conventions, and pricing structures.

### Decision

Each provider is a separate module under `src/providers.py` implementing a common interface:

```python
class LLMProvider(Protocol):
    async def chat_completion(self, request: ChatRequest) -> ChatResponse: ...
    def resolve_model(self, model_alias: str) -> str: ...
    def estimate_cost(self, model: str, tokens: int) -> float: ...
```

### Rationale

- **Extensible:** Adding a new provider = adding a new module, zero changes to core engine.
- **Testable:** Each provider can be mocked independently.
- **Cost-aware:** The `estimate_cost` method enables budget enforcement before the request is sent.

### Constraints

- Provider auto-detection is based on URL patterns. No magic.
- Price data is cached locally (`src/price_cache.py`) with TTL to avoid runtime API calls.
# ADR-006: Revenue Architecture — License Keys over Subscriptions

**Status:** Draft
**Date:** 2026-05-29

## Context

ResGov needed a monetization mechanism. The initial concept was a one-time purchase (~€250). This does not produce recurring revenue and requires manual invoicing per customer.

## Decision

Implement a **license key system** with tiered products:

| Product | Model | Target |
|---------|-------|--------|
| Community | Free (BSL) | Adoption & network effect |
| Pro | Recurring license key (monthly) | Primary revenue |
| Enterprise | Custom license key | High-value customers |

License keys are:
- Generated via `POST /api/v1/admin/licenses`
- Validated at agent registration (agent limit enforcement)
- Stored as SHA-256 hashes (never plaintext)
- Revocable via admin API

**Why not Stripe subscriptions directly:**
- Self-hosted software can't enforce subscription checks without phone-home (privacy concern)
- License keys work offline — customers self-host, keys have TTL
- Stripe can be added later as the payment layer (Phase 2)

**Why not pure open-source (no license):**
- BSL-1.1 already prevents commercial competitors from using the code freely
- License keys create a conversion funnel: Community → Pro
- Production usage (multi-tenant) is the paid feature

## Consequences

- ✅ Works offline (no phone-home)
- ✅ Stripe can be integrated later without architectural change
- ✅ Agent-limit enforcement built into registration flow
- ❌ License keys can be shared (mitigation: machine_id binding, TTL)
- ❌ No automatic payment collection (manual invoicing until Stripe integration)

## Alternatives Considered

| Alternative | Reason Rejected |
|-------------|-----------------|
| Pure donation / "sponsor" | Not sustainable for full-time development |
| Stripe Subscriptions only | Violates self-hosted privacy model |
| Open Source (MIT/Apache) | No monetization, competitors can commercialize |
| SaaS-only (no self-host) | Excludes EU/DSGVO-conscious customers |
