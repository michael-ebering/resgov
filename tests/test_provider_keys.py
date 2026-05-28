"""Tests for provider-scoped API keys (I6) and price cache (I1)."""
import os
import sqlite3
import pytest
import threading


from src.auth import create_api_key, verify_api_key, _hash_key, init_api_keys_table


class TestProviderScopedKeys:
    def setup_method(self):
        """Clear any cached DB connection between tests."""
        import src.auth as auth_mod
        auth_mod._local = threading.local()
        import src.models as models_mod
        models_mod._local = threading.local()
        import src.middleware as middleware_mod
        middleware_mod._local = threading.local()

    def _setup_db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        os.environ["RESGOV_DB_PATH"] = db_path
        os.environ["RESGOV_ADMIN_TOKEN"] = "test-admin-token"
        db = sqlite3.connect(db_path)
        db.execute("PRAGMA journal_mode=WAL")
        from src.models import init_db
        init_db(db)
        db.close()
        # Reconnect through middleware to init api_keys table
        db2 = sqlite3.connect(db_path)
        db2.execute("PRAGMA journal_mode=WAL")
        from src.auth import init_api_keys_table
        init_api_keys_table()
        db2.close()
        return db_path

    def test_create_key_with_provider_all(self, tmp_path):
        self._setup_db(tmp_path)
        key = create_api_key(owner="test", org_id="org1", provider="all")
        assert key.startswith("rgv_")
        # Should work for any provider
        result = verify_api_key(key, provider="openai")
        assert result["provider"] == "all"
        result = verify_api_key(key, provider="anthropic")
        assert result["provider"] == "all"

    def test_create_key_with_specific_provider(self, tmp_path):
        self._setup_db(tmp_path)
        key = create_api_key(owner="test", org_id="org1", provider="openai")
        # Should work for openai
        result = verify_api_key(key, provider="openai")
        assert result["provider"] == "openai"
        # Should NOT work for anthropic
        with pytest.raises(Exception) as exc_info:
            verify_api_key(key, provider="anthropic")
        assert "not authorized for provider" in str(exc_info.value).lower() or "403" in str(exc_info.value)

    def test_create_key_with_anthropic_provider(self, tmp_path):
        self._setup_db(tmp_path)
        key = create_api_key(owner="test", org_id="org1", provider="anthropic")
        result = verify_api_key(key, provider="anthropic")
        assert result["provider"] == "anthropic"
        with pytest.raises(Exception):
            verify_api_key(key, provider="openai")

    def test_key_scoping_openai_vs_anthropic(self, tmp_path):
        """Provider-scoped key should only work for its provider."""
        self._setup_db(tmp_path)
        # Create two keys: one for openai, one for anthropic
        openai_key = create_api_key(owner="test", org_id="org1", provider="openai")
        anthropic_key = create_api_key(owner="test", org_id="org1", provider="anthropic")

        # Openai key works for openai
        result = verify_api_key(openai_key, provider="openai")
        assert result["provider"] == "openai"

        # Openai key rejected for anthropic
        with pytest.raises(Exception):
            verify_api_key(openai_key, provider="anthropic")

        # Anthropic key works for anthropic
        result = verify_api_key(anthropic_key, provider="anthropic")
        assert result["provider"] == "anthropic"

        # Anthropic key rejected for openai
        with pytest.raises(Exception):
            verify_api_key(anthropic_key, provider="openai")

    def test_invalid_key_rejected(self, tmp_path):
        self._setup_db(tmp_path)
        with pytest.raises(Exception):
            verify_api_key("rgv_invalidkey", provider="openai")

    def test_missing_key_rejected(self, tmp_path):
        self._setup_db(tmp_path)
        with pytest.raises(Exception):
            verify_api_key(None, provider="openai")


class TestPriceCache:
    def _setup_db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        os.environ["RESGOV_DB_PATH"] = db_path
        db = sqlite3.connect(db_path)
        db.execute("PRAGMA journal_mode=WAL")
        from src.models import init_db
        init_db(db)
        db.close()
        return db_path

    def test_price_cache_table_exists(self, tmp_path):
        self._setup_db(tmp_path)
        db_path = os.environ["RESGOV_DB_PATH"]
        db = sqlite3.connect(db_path)
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='price_cache'").fetchall()
        assert len(tables) == 1
        db.close()

    def test_price_cache_empty_initially(self, tmp_path):
        self._setup_db(tmp_path)
        from src.price_cache import get_cached_price, _get_merged_price_table
        assert get_cached_price("openai/gpt-4o") is None
        assert _get_merged_price_table() == {}

    def test_price_cache_write_and_read(self, tmp_path):
        self._setup_db(tmp_path)
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

    def test_merged_price_table_overrides_defaults(self, tmp_path):
        self._setup_db(tmp_path)
        from src.price_cache import update_price_cache, _get_merged_price_table
        # Cache a custom price
        update_price_cache({"openai/gpt-4o": {"input": 0.000005, "output": 0.000020}})
        merged = _get_merged_price_table()
        # Should have cached price for gpt-4o
        assert merged["openai/gpt-4o"]["input"] == 0.000005
        # Should still have default for other models
        assert "anthropic/claude-sonnet-4" in merged

    def test_price_cache_update_overwrites(self, tmp_path):
        self._setup_db(tmp_path)
        from src.price_cache import update_price_cache, get_cached_price
        update_price_cache({"openai/gpt-4o": {"input": 0.0000025, "output": 0.000010}})
        update_price_cache({"openai/gpt-4o": {"input": 0.000005, "output": 0.000020}})
        cached = get_cached_price("openai/gpt-4o")
        assert cached["input"] == 0.000005  # Updated value
