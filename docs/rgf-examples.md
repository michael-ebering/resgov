# `.rgf` Configuration Examples

> Real-world configuration examples for different deployment scenarios.

## Table of Contents

- [Basic Single-Agent Setup](#basic-single-agent-setup)
- [Multi-Agent Development Team](#multi-agent-development-team)
- [CI/CD Pipeline Agents](#cicd-pipeline-agents)
- [Production with Model Restrictions](#production-with-model-restrictions)
- [Budget-Conscious Startup](#budget-conscious-startup)
- [Enterprise Multi-Tenant](#enterprise-multi-tenant)
- [GitHub Copilot as LLM Provider](#github-copilot-as-llm-provider)

---

## Basic Single-Agent Setup

For a single developer running one agent locally:

```toml
[global]
currency = "USD"
fail_safe_action = "deny"

[agents.dev-agent]
daily_budget = 5.00
max_tokens_per_request = 8192
allowed_models = [
    "openrouter/anthropic/claude-sonnet-4-6",
    "openrouter/deepseek/deepseek-v4-flash",
    "openrouter/google/gemini-3-5-flash"
]
```

---

## Multi-Agent Development Team

Three agents with different roles and budgets:

```toml
[global]
currency = "USD"
fail_safe_action = "deny"

[agents.coder]
daily_budget = 8.00
max_tokens_per_request = 16384
allowed_models = [
    "openrouter/anthropic/claude-opus-4-7",
    "openrouter/openai/gpt-5-4",
    "openrouter/x-ai/grok-build-0-1"
]
allowed_tools = ["web_search", "code_exec", "file_read", "git"]

[agents.reviewer]
daily_budget = 3.00
max_tokens_per_request = 8192
allowed_models = [
    "openrouter/anthropic/claude-sonnet-4-6",
    "openrouter/google/gemini-3-5-flash"
]
allowed_tools = ["web_search", "file_read", "git"]

[agents.researcher]
daily_budget = 4.00
max_tokens_per_request = 4096
allowed_models = [
    "openrouter/deepseek/deepseek-v4-flash",
    "openrouter/qwen/qwen3-7-max",
    "openrouter/google/gemini-3-5-flash"
]
allowed_tools = ["web_search", "web_scraper", "file_read"]
```

---

## CI/CD Pipeline Agents

Automated agents for CI/CD with tight budgets and restricted models:

```toml
[global]
currency = "USD"
fail_safe_action = "deny"

[agents.ci-test-runner]
daily_budget = 2.00
max_tokens_per_request = 4096
allowed_models = [
    "openrouter/deepseek/deepseek-v4-flash",
    "openrouter/openai/gpt-5-4-mini"
]
allowed_tools = ["code_exec", "file_read", "git"]

[agents.ci-deployer]
daily_budget = 1.00
max_tokens_per_request = 2048
allowed_models = [
    "openrouter/deepseek/deepseek-v4-flash"
]
allowed_tools = ["code_exec", "git"]

[agents.pr-reviewer]
daily_budget = 3.00
max_tokens_per_request = 8192
allowed_models = [
    "openrouter/anthropic/claude-sonnet-4-6",
    "openrouter/google/gemini-3-1-pro"
]
allowed_tools = ["file_read", "git", "web_search"]
```

---

## Production with Model Restrictions

Restrict to specific model tiers for cost control:

```toml
[global]
currency = "USD"
fail_safe_action = "deny"

[agents.prod-primary]
daily_budget = 20.00
monthly_budget = 400.00
max_tokens_per_request = 16384
allowed_models = [
    # Premium tier — only for complex reasoning
    "openrouter/anthropic/claude-opus-4-7",
    "openrouter/openai/gpt-5-5",
    # Standard tier — daily work
    "openrouter/anthropic/claude-sonnet-4-6",
    "openrouter/google/gemini-3-5-flash",
    # Fast tier — simple tasks
    "openrouter/deepseek/deepseek-v4-flash",
    "openrouter/openai/gpt-5-4-mini"
]
allowed_tools = ["web_search", "code_exec", "file_read", "git", "web_scraper"]

[agents.prod-secondary]
daily_budget = 5.00
monthly_budget = 100.00
max_tokens_per_request = 8192
allowed_models = [
    # No premium tier for secondary agents
    "openrouter/anthropic/claude-sonnet-4-6",
    "openrouter/google/gemini-3-5-flash",
    "openrouter/deepseek/deepseek-v4-flash"
]
allowed_tools = ["web_search", "file_read"]
```

---

## Budget-Conscious Startup

Maximize free and cheap models:

```toml
[global]
currency = "USD"
fail_safe_action = "allow"  # Allow through if budget system fails

[agents.main]
daily_budget = 2.00
max_tokens_per_request = 8192
allowed_models = [
    # Free tier models (OpenRouter :free suffix)
    "openrouter/meta-llama/llama-3-3-70b-instruct:free",
    "openrouter/deepseek/deepseek-r1:free",
    "openrouter/qwen/qwen3-next-80b-a3b-instruct:free",
    "openrouter/google/gemma-4-26b-a4b-it:free",
    # Cheap paid fallback
    "openrouter/deepseek/deepseek-v4-flash",
    "openrouter/openai/gpt-oss-120b:free"
]
allowed_tools = ["web_search", "code_exec", "file_read"]
```

---

## Enterprise Multi-Tenant

Multiple organizations with isolated budgets:

```toml
[global]
currency = "USD"
fail_safe_action = "deny"

# Organization A — Engineering team
[agents.org-a-coder]
daily_budget = 15.00
monthly_budget = 300.00
max_tokens_per_request = 16384
allowed_models = [
    "openrouter/anthropic/claude-opus-4-7",
    "openrouter/anthropic/claude-sonnet-4-6",
    "openrouter/openai/gpt-5-4",
    "openrouter/google/gemini-3-5-flash"
]
allowed_tools = ["web_search", "code_exec", "file_read", "git", "web_scraper"]

[agents.org-a-reviewer]
daily_budget = 5.00
monthly_budget = 100.00
max_tokens_per_request = 8192
allowed_models = [
    "openrouter/anthropic/claude-sonnet-4-6",
    "openrouter/google/gemini-3-1-pro"
]
allowed_tools = ["file_read", "git"]

# Organization B — Marketing team (lower budget)
[agents.org-b-writer]
daily_budget = 3.00
monthly_budget = 60.00
max_tokens_per_request = 4096
allowed_models = [
    "openrouter/anthropic/claude-sonnet-4-6",
    "openrouter/google/gemini-3-5-flash",
    "openrouter/deepseek/deepseek-v4-flash"
]
allowed_tools = ["web_search", "file_read"]

[agents.org-b-analyst]
daily_budget = 2.00
monthly_budget = 40.00
max_tokens_per_request = 4096
allowed_models = [
    "openrouter/deepseek/deepseek-v4-flash",
    "openrouter/google/gemini-3-5-flash"
]
allowed_tools = ["web_search", "web_scraper"]
```

---

## GitHub Copilot as LLM Provider

Use GitHub Copilot models through ResGov. GitHub Copilot uses a different auth flow (OAuth token via `api.githubcopilot.com`) and has its own pricing model.

### Available GitHub Copilot Models (as of May 2026)

| Model | Provider | Tier | Multiplier |
|-------|----------|------|------------|
| GPT-5.5 | OpenAI | Premium | 7.5x |
| GPT-5.4 | OpenAI | Standard | 1x |
| GPT-5.4 mini | OpenAI | Fast | 0.33x |
| GPT-5.3-Codex | OpenAI | Standard | 1x |
| GPT-5.2 | OpenAI | Standard | 1x |
| GPT-5 mini | OpenAI | Free | 0x |
| GPT-4.1 | OpenAI | Free | 0x |
| Claude Opus 4.7 | Anthropic | Premium | 15x |
| Claude Opus 4.6 | Anthropic | Premium | 3x |
| Claude Opus 4.5 | Anthropic | Premium | 3x |
| Claude Sonnet 4.6 | Anthropic | Standard | 1x |
| Claude Sonnet 4.5 | Anthropic | Standard | 1x |
| Claude Haiku 4.5 | Anthropic | Fast | 0.33x |
| Gemini 3.5 Flash | Google | Premium | 14x |
| Gemini 3.1 Pro | Google | Standard | 1x |
| Gemini 3 Flash | Google | Fast | 0.33x |
| Gemini 2.5 Pro | Google | Standard | 1x |

> **Note:** GitHub Copilot is transitioning to usage-based billing (token-based) in June 2026. Model multipliers will be replaced by per-token pricing. See [GitHub Copilot Billing](https://docs.github.com/en/copilot/concepts/billing/usage-based-billing-for-individuals).

### GitHub Copilot `.rgf` Configuration

```toml
[global]
currency = "USD"
fail_safe_action = "deny"

[agents.copilot-dev]
daily_budget = 10.00
max_tokens_per_request = 16384
# GitHub Copilot model names (as used in api.githubcopilot.com)
allowed_models = [
    "gpt-5-4",
    "gpt-5-4-mini",
    "gpt-5-3-codex",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "gemini-2-5-pro",
    "gemini-3-5-flash"
]
allowed_tools = ["web_search", "code_exec", "file_read", "git"]
```

### GitHub Copilot Auth Setup

GitHub Copilot requires an OAuth token (not an API key). To use it with ResGov:

1. Generate a GitHub OAuth token with `copilot` scope
2. Set it as `GITHUB_COPILOT_TOKEN` in your `.env`
3. ResGov routes requests to `https://api.githubcopilot.com/chat/completions`

```bash
# .env
GITHUB_COPILOT_TOKEN=github_oauth_token_here
```

### GitHub Copilot Pricing Tiers (May 2026)

| Plan | Price | Premium Requests | Notes |
|------|-------|-----------------|-------|
| Free | $0 | 50/mo | 2,000 completions + GPT-4.1/GPT-4o unlimited chat |
| Pro | $10/mo | 300/mo | Full model access |
| Pro+ | $39/mo | 1,500/mo | Highest tier for individuals |
| Business | $19/user/mo | 300/user/mo | Org-level management |
| Enterprise | $39/user/mo | 1,000/user/mo | SSO, audit logs, policy controls |

> **Important:** Premium requests are consumed based on model multipliers. A single Claude Opus 4.7 request costs 15 premium requests. GPT-5 mini and GPT-4.1 are free (0 multiplier).

---

## Parameter Reference

### Global Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `currency` | string | `"USD"` | Budget currency for display |
| `fail_safe_action` | string | `"deny"` | Behavior when budget system fails: `"deny"` (block all) or `"allow"` (pass through) |

### Agent Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `daily_budget` | float | unlimited | Maximum daily spend in USD |
| `monthly_budget` | float | unlimited | Maximum monthly spend in USD |
| `max_tokens_per_request` | int | unlimited | Maximum tokens per LLM request |
| `allowed_models` | list | all models | Whitelist of model IDs (OpenRouter or GitHub Copilot format) |
| `allowed_tools` | list | all tools | Whitelist of tool names the agent can use |

### Model ID Formats

**OpenRouter format:** `provider/model-id`
```toml
allowed_models = [
    "openrouter/anthropic/claude-opus-4-7",
    "openrouter/deepseek/deepseek-v4-flash",
    "openrouter/google/gemini-3-5-flash",
    "openrouter/openai/gpt-5-4",
    "openrouter/qwen/qwen3-7-max",
    "openrouter/x-ai/grok-build-0-1"
]
```

**OpenRouter free tier:** Append `:free` to model ID
```toml
allowed_models = [
    "openrouter/deepseek/deepseek-r1:free",
    "openrouter/meta-llama/llama-3-3-70b-instruct:free"
]
```

**GitHub Copilot format:** Use model name directly
```toml
allowed_models = [
    "gpt-5-4",
    "claude-sonnet-4-6",
    "gemini-2-5-pro"
]
```
