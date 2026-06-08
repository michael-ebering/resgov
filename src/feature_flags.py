"""
ResGov — Feature Flags & Tier Definitions

Defines which features are available in each subscription tier.
Used by the @require_tier decorator and engine-level checks.

Tiers:
  community  — Free, open-source, single-tenant, basic features
  pro        — €29/mo, multi-tenant, advanced features, higher limits
  enterprise — Custom pricing, unlimited, all features
"""
from enum import Enum
from typing import Set


class Tier(Enum):
    COMMUNITY = "community"
    PRO = "pro"
    ENTERPRISE = "enterprise"


# ── Feature definitions ────────────────────────────────────────────────────

# Each feature maps to the minimum tier required to use it.
# Features not listed are available to all tiers.

FEATURES = {
    # ── Community (free) ────────────────────────────────────────────────
    "proxy_basic": Tier.COMMUNITY,
    "proxy_streaming": Tier.COMMUNITY,
    "budget_daily": Tier.COMMUNITY,
    "budget_monthly": Tier.COMMUNITY,
    "agents_register": Tier.COMMUNITY,
    "agents_list": Tier.COMMUNITY,
    "agents_get": Tier.COMMUNITY,
    "agents_update_budget": Tier.COMMUNITY,
    "agents_delete": Tier.COMMUNITY,
    "book_resource": Tier.COMMUNITY,
    "usage_stats": Tier.COMMUNITY,
    "audit_trail": Tier.COMMUNITY,
    "health_check": Tier.COMMUNITY,
    "metrics_prometheus": Tier.COMMUNITY,
    "rgf_config": Tier.COMMUNITY,
    "dashboard_basic": Tier.COMMUNITY,
    "api_keys_manage": Tier.COMMUNITY,
    "price_cache": Tier.COMMUNITY,

    # ── Pro (€29/mo) ────────────────────────────────────────────────────
    "multi_tenant": Tier.PRO,
    "webhooks": Tier.PRO,
    "predictive_forecasting": Tier.PRO,
    "dashboard_advanced": Tier.PRO,
    "license_management": Tier.PRO,
    "non_llm_booking": Tier.PRO,
    "budget_total": Tier.PRO,
    "admin_reset_daily": Tier.PRO,
    "admin_reset_monthly": Tier.PRO,
    "admin_generate_keys": Tier.PRO,
    "admin_revoke_keys": Tier.PRO,
    "admin_audit_full": Tier.PRO,
    "admin_price_cache_refresh": Tier.PRO,
    "admin_license_create": Tier.PRO,
    "admin_license_revoke": Tier.PRO,
    "admin_license_status": Tier.PRO,

    # ── Enterprise (custom) ─────────────────────────────────────────────
    "sso": Tier.ENTERPRISE,
    "rbac": Tier.ENTERPRISE,
    "opa_integration": Tier.ENTERPRISE,
    "custom_retention": Tier.ENTERPRISE,
    "sla": Tier.ENTERPRISE,
    "dedicated_support": Tier.ENTERPRISE,
}

# ── Tier limits ────────────────────────────────────────────────────────────

TIER_LIMITS = {
    Tier.COMMUNITY: {
        "max_agents": 5,
        "max_orgs": 1,
        "max_requests_per_day": 10_000,
        "max_api_keys": 3,
        "max_webhooks": 0,
        "max_reserved_budget": 100.0,  # USD
        "audit_retention_days": 7,
        "support": "community",
    },
    Tier.PRO: {
        "max_agents": 50,
        "max_orgs": 5,
        "max_requests_per_day": 100_000,
        "max_api_keys": 20,
        "max_webhooks": 5,
        "max_reserved_budget": 10_000.0,
        "audit_retention_days": 90,
        "support": "email",
    },
    Tier.ENTERPRISE: {
        "max_agents": -1,  # unlimited
        "max_orgs": -1,
        "max_requests_per_day": -1,
        "max_api_keys": -1,
        "max_webhooks": -1,
        "max_reserved_budget": -1,
        "audit_retention_days": 365,
        "support": "dedicated",
    },
}


def get_min_tier(feature: str) -> Tier:
    """Get the minimum tier required for a feature."""
    return FEATURES.get(feature, Tier.COMMUNITY)


def is_feature_available(feature: str, tier: Tier) -> bool:
    """Check if a feature is available for a given tier."""
    min_tier = get_min_tier(feature)
    tier_order = [Tier.COMMUNITY, Tier.PRO, Tier.ENTERPRISE]
    return tier_order.index(tier) >= tier_order.index(min_tier)


def get_tier_limits(tier: Tier) -> dict:
    """Get all limits for a tier."""
    return TIER_LIMITS.get(tier, TIER_LIMITS[Tier.COMMUNITY])


def get_features_for_tier(tier: Tier) -> Set[str]:
    """Get all features available for a tier."""
    return {f for f in FEATURES if is_feature_available(f, tier)}


def get_features_not_available(tier: Tier) -> Set[str]:
    """Get features NOT available for a tier (for upgrade prompts)."""
    return {f for f in FEATURES if not is_feature_available(f, tier)}
