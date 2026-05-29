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
