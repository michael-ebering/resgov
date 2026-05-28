"""Tests for provider-scoped API keys (I6) and price cache (I1)."""
import os
import pytest

from src.auth import create_api_key, verify_api_key, _hash_key, init_api_keys_table
from src.middleware import get_db


@pytest.fixture(autouse=True)
def _use_module_db():
    """Ensure the module_db fixture from conftest.py is active."""
    db = get_db()
    init_api_keys_table()
    yield


class TestProviderScopedKeys:
    def test_create_key_with_provider_all(self):
        key = create_api_key(owner="test", org_id="org1", provider="all")
        assert key.startswith("rgv_")
        result = verify_api_key(key, provider="openai")
        assert result["provider"] == "all"
        result = verify_api_key(key, provider="anthropic")
        assert result["provider"] == "all"

    def test_create_key_with_specific_provider(self):
        key = create_api_key(owner="test", org_id="org1", provider="openai")
        result = verify_api_key(key, provider="openai")
        assert result["provider"] == "openai"
        with pytest.raises(Exception) as exc_info:
            verify_api_key(key, provider="anthropic")
        assert "not authorized for provider" in str(exc_info.value).lower() or "403" in str(exc_info.value)

    def test_create_key_with_anthropic_provider(self):
        key = create_api_key(owner="test", org_id="org1", provider="anthropic")
        result = verify_api_key(key, provider="anthropic")
        assert result["provider"] == "anthropic"
        with pytest.raises(Exception):
            verify_api_key(key, provider="openai")

    def test_key_scoping_openai_vs_anthropic(self):
        """Provider-scoped key should only work for its provider."""
        openai_key = create_api_key(owner="test", org_id="org1", provider="openai")
        anthropic_key = create_api_key(owner="test", org_id="org1", provider="anthropic")
        result = verify_api_key(openai_key, provider="openai")
        assert result["provider"] == "openai"
        with pytest.raises(Exception):
            verify_api_key(openai_key, provider="anthropic")
        result = verify_api_key(anthropic_key, provider="anthropic")
        assert result["provider"] == "anthropic"
        with pytest.raises(Exception):
            verify_api_key(anthropic_key, provider="openai")

    def test_invalid_key_rejected(self):
        with pytest.raises(Exception):
            verify_api_key("rgv_invalidkey", provider="openai")

    def test_missing_key_rejected(self):
        with pytest.raises(Exception):
            verify_api_key(None, provider="openai")


class TestPriceCache:
    def test_price_cache_table_exists(self):
        db = get_db()
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='price_cache'").fetchall()
        assert len(tables) == 1

    def test_price_cache_empty_initially(self):
        from src.price_cache import get_cached_price, _get_merged_price_table
        assert get_cached_price("openai/gpt-4o") is None
        assert _get_merged_price_table() == {}

    def test_price_cache_write_and_read(self):
        from src.price_cache import update_price_cache, get_cached_price, _get_merged_price_table
        prices = {
            "openai/gpt-4o": {"input": 0.0000025, "output": 0.000010},
            "anthropic/claude-sonnet-4": {"input": 0.000003, "output": 0.000015},
        }
        updated = update_price_cache(prices)
        assert updated == 2
        cached = get_cached_price("openai/gpt-4o")
        assert cached is not None
        assert cached["input"] == 0.0000025
        assert cached["output"] == 0.000010

    def test_merged_price_table_overrides_defaults(self):
        from src.price_cache import update_price_cache, _get_merged_price_table
        update_price_cache({"openai/gpt-4o": {"input": 0.000005, "output": 0.000020}})
        merged = _get_merged_price_table()
        assert merged["openai/gpt-4o"]["input"] == 0.000005
        assert "anthropic/claude-sonnet-4" in merged

    def test_price_cache_update_overwrites(self):
        from src.price_cache import update_price_cache, get_cached_price
        update_price_cache({"openai/gpt-4o": {"input": 0.0000025, "output": 0.000010}})
        update_price_cache({"openai/gpt-4o": {"input": 0.000005, "output": 0.000020}})
        cached = get_cached_price("openai/gpt-4o")
        assert cached["input"] == 0.000005  # Updated value
