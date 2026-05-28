"""Tests for improved token estimation (I5) and cost tracking (I3+I4)."""
import pytest
from src.api import _estimate_input_tokens, _estimate_max_cost, _extract_usage_from_response
from src.engine import BudgetEngine


class TestEstimateInputTokens:
    def test_english_prose(self):
        # ~4 chars per token for English
        msgs = [{"content": "a" * 4000}]
        result = _estimate_input_tokens(msgs)
        assert 900 <= result <= 1100  # ~1000

    def test_german_text(self):
        # ~3.2 chars per token for German (more compound words)
        msgs = [{"content": "Dies ist ein deutscher Text mit Umlauten ä ö ü ß" * 100}]
        result = _estimate_input_tokens(msgs)
        assert result > 1000  # More tokens than English for same char count

    def test_json_code(self):
        # ~3 chars per token for JSON/code
        msgs = [{"content": '{"key": "value", "nested": {"a": 1}}' * 200}]
        result = _estimate_input_tokens(msgs)
        assert result > 1200

    def test_empty_messages(self):
        result = _estimate_input_tokens([])
        assert result == 128  # minimum

    def test_empty_content(self):
        result = _estimate_input_tokens([{"content": ""}])
        assert result == 128  # minimum

    def test_multiple_messages(self):
        msgs = [
            {"content": "Hello " * 100},
            {"content": "World " * 100},
        ]
        result = _estimate_input_tokens(msgs)
        assert result > 200  # Combined text

    def test_special_chars_below_threshold(self):
        # Not enough special chars to trigger JSON heuristic
        msgs = [{"content": "Hello world this is normal text " * 50}]
        result = _estimate_input_tokens(msgs)
        # Should use English heuristic: 1500 chars / 4 = ~375
        assert 350 <= result <= 450


class TestExtractUsageFromResponse:
    def test_openai_format(self):
        resp = {"usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}
        result = _extract_usage_from_response(resp)
        assert result == {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}

    def test_anthropic_format(self):
        resp = {"usage": {"input_tokens": 200, "output_tokens": 100}}
        result = _extract_usage_from_response(resp)
        assert result == {"input_tokens": 200, "output_tokens": 100, "total_tokens": 300}

    def test_google_format(self):
        resp = {"usageMetadata": {"promptTokenCount": 300, "candidatesTokenCount": 150, "totalTokenCount": 450}}
        result = _extract_usage_from_response(resp)
        assert result == {"input_tokens": 300, "output_tokens": 150, "total_tokens": 450}

    def test_no_usage(self):
        resp = {"choices": [{"message": {"content": "hello"}}]}
        result = _extract_usage_from_response(resp)
        assert result == {}

    def test_google_takes_priority(self):
        """If both usageMetadata and usage exist, Google format should win."""
        resp = {
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15},
            "usage": {"prompt_tokens": 999, "completion_tokens": 999},
        }
        result = _extract_usage_from_response(resp)
        assert result["input_tokens"] == 10

    def test_openai_alternative_keys(self):
        """Some providers use input_tokens/output_tokens instead of prompt/completion."""
        resp = {"usage": {"input_tokens": 75, "output_tokens": 25}}
        result = _extract_usage_from_response(resp)
        assert result == {"input_tokens": 75, "output_tokens": 25, "total_tokens": 100}


class TestCostCalculationWithSeparatePricing:
    """Test that _estimate_max_cost uses separate input/output pricing."""

    def test_openai_gpt4o_pricing(self):
        price_table = {
            "openai/gpt-4o": {"input": 0.0000025, "output": 0.000010},
            "default": {"input": 0.000001, "output": 0.000003},
        }
        messages = [{"content": "a" * 4000}]  # ~1000 tokens
        result = _estimate_max_cost("openai/gpt-4o", 500, price_table, messages=messages)
        # ~1000 * 2.5e-6 + 500 * 1.0e-5 = 0.0025 + 0.005 = 0.0075
        assert 0.005 <= result <= 0.015  # Rough range due to estimation

    def test_cheap_model(self):
        price_table = {
            "default": {"input": 0.0000001, "output": 0.0000003},
        }
        result = _estimate_max_cost("some/cheap-model", 1000, price_table, messages=[{"content": "a" * 400}])
        # ~100 * 1e-7 + 1000 * 3e-7 = 0.00001 + 0.0003 = 0.00031
        assert 0.0001 <= result <= 0.001


class TestReserveFinalizeCostTracking:
    """Integration test: reserve → finalize should track estimated vs actual."""

    def _make_engine(self, db, daily_limit=10.0, monthly_limit=100.0):
        engine = BudgetEngine(rgf_config={}, db=db)
        engine.register_agent("test-agent", "Test", daily_limit=daily_limit, monthly_limit=monthly_limit)
        return engine

    def test_estimated_gte_actual(self, tmp_path):
        import sqlite3, os
        db_path = str(tmp_path / "test.db")
        os.environ["RESGOV_DB_PATH"] = db_path
        db = sqlite3.connect(db_path)
        db.execute("PRAGMA journal_mode=WAL")
        from src.models import init_db
        init_db(db)
        # Reconnect to pick up schema
        db.close()
        db = sqlite3.connect(db_path)
        db.execute("PRAGMA journal_mode=WAL")
        db.row_factory = sqlite3.Row

        engine = self._make_engine(db, daily_limit=10.0, monthly_limit=100.0)

        # Reserve with max cost
        res = engine.reserve_budget("test-agent", 0.50, model="openai/gpt-4o", max_tokens=1000)
        assert res["status"] == "reserved"

        # Finalize with lower actual cost
        fin = engine.finalize_budget("test-agent", 0.50, 0.30)
        assert fin["status"] == "finalized"
        assert fin["refund"] == 0.20

        # Check bookings
        bookings = db.execute("SELECT * FROM bookings WHERE agent_id = 'test-agent' ORDER BY id").fetchall()
        assert len(bookings) == 2  # reserve + finalize
        reserve_booking = bookings[0]
        finalize_booking = bookings[1]
        assert reserve_booking["estimated_cost"] == 0.50
        assert finalize_booking["estimated_cost"] == 0.50
        assert finalize_booking["actual_cost"] == 0.30

        # Check budget: only 0.30 should be spent
        budgets = db.execute("SELECT * FROM budgets WHERE agent_id = 'test-agent' AND period = 'daily'").fetchone()
        assert budgets["spent_amount"] == 0.30  # Not 0.50

        db.close()

    def test_actual_exceeds_reserved(self, tmp_path):
        """Underpayment case: actual > reserved."""
        import sqlite3, os
        db_path = str(tmp_path / "test.db")
        os.environ["RESGOV_DB_PATH"] = db_path
        db = sqlite3.connect(db_path)
        db.execute("PRAGMA journal_mode=WAL")
        from src.models import init_db
        init_db(db)
        db.close()
        db = sqlite3.connect(db_path)
        db.execute("PRAGMA journal_mode=WAL")
        db.row_factory = sqlite3.Row

        engine = self._make_engine(db, daily_limit=10.0, monthly_limit=100.0)

        res = engine.reserve_budget("test-agent", 0.10, model="openai/gpt-4o", max_tokens=100)
        assert res["status"] == "reserved"

        # Actual cost exceeds reserved (underestimation)
        fin = engine.finalize_budget("test-agent", 0.10, 0.25)
        assert fin["status"] == "finalized"
        assert fin["refund"] == -0.15  # Negative = overdraft

        db.close()
