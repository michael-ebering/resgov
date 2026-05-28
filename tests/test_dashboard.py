"""Tests for dashboard endpoints: /dash/api/stats, /dash/api/agents, /dash/api/bookings."""
import os
import pytest
import tempfile
import json
import hmac
import hashlib

# Set up test DB before imports
db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)

os.environ["RESGOV_DB_PATH"] = db_path
os.environ["RESGOV_API_KEYS"] = ""
os.environ["RESGOV_ADMIN_TOKEN"] = "test-admin-token"
os.environ["RESGOV_DASH_USER"] = "admin"
os.environ["RESGOV_DASH_PASS"] = ""

from src.models import init_db
from src.engine import BudgetEngine
from src.auth import init_api_keys_table
from src.middleware import ConnectionPool, get_db


def setup_module():
    db = get_db()
    init_db(db)
    init_api_keys_table()


@pytest.fixture(scope="module")
def engine():
    eng = BudgetEngine()
    yield eng


def _register_agent(engine, agent_id="test-agent", daily=10.0, monthly=100.0):
    engine.register_agent(agent_id=agent_id, name=f"Agent {agent_id}", daily_limit=daily, monthly_limit=monthly)


class TestDashboardStats:
    def test_stats_structure(self, engine):
        """Verify stats returns expected keys."""
        _register_agent(engine, "stats-agent-1")
        from starlette.testclient import TestClient
        from src.api import app
        client = TestClient(app)
        resp = client.get("/dash/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        assert "bookings" in data
        assert "costs" in data
        assert "metrics" in data
        assert data["agents"]["total"] >= 1

    def test_stats_costs(self, engine):
        """Test that reserved/actual costs are tracked."""
        _register_agent(engine, "cost-agent", daily=10.0, monthly=100.0)
        engine.book("cost-agent", action="test_call", cost=0.50)
        from starlette.testclient import TestClient
        from src.api import app
        client = TestClient(app)
        resp = client.get("/dash/api/stats")
        data = resp.json()
        assert data["bookings"]["total"] >= 1
        assert data["costs"]["total_spent"] >= 0.50
        client.close()


class TestDashboardAgents:
    def test_agents_list(self, engine):
        """Verify agents list returns agent data with budget info."""
        _register_agent(engine, "list-agent-1", daily=5.0, monthly=50.0)
        _register_agent(engine, "list-agent-2", daily=3.0, monthly=30.0)
        from starlette.testclient import TestClient
        from src.api import app
        client = TestClient(app)
        resp = client.get("/dash/api/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2
        agent_ids = [a["agent_id"] for a in data]
        assert "list-agent-1" in agent_ids
        assert "list-agent-2" in agent_ids

    def test_agent_budget_bars(self, engine):
        """Agent should have daily/monthly limit and remaining."""
        _register_agent(engine, "bar-agent", daily=10.0, monthly=100.0)
        engine.book("bar-agent", action="test", cost=2.00)
        from starlette.testclient import TestClient
        from src.api import app
        client = TestClient(app)
        resp = client.get("/dash/api/agents")
        data = resp.json()
        bar_agent = next(a for a in data if a["agent_id"] == "bar-agent")
        assert bar_agent["daily_limit"] == 10.0
        assert bar_agent["monthly_limit"] == 100.0
        client.close()


class TestDashboardBookings:
    def test_bookings_list(self, engine):
        """Verify bookings endpoint returns recent bookings."""
        _register_agent(engine, "book-agent", daily=10.0, monthly=100.0)
        engine.book("book-agent", action="chat", cost=0.10)
        engine.book("book-agent", action="compute", cost=0.20)
        from starlette.testclient import TestClient
        from src.api import app
        client = TestClient(app)
        resp = client.get("/dash/api/bookings")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2

    def test_bookings_filter_status(self, engine):
        """Filter bookings by status."""
        _register_agent(engine, "filter-agent", daily=0.05, monthly=100.0)
        engine.book("filter-agent", action="ok", cost=0.01)
        engine.book("filter-agent", action="denied", cost=1.00)
        from starlette.testclient import TestClient
        from src.api import app
        client = TestClient(app)
        resp = client.get("/dash/api/bookings?status=denied")
        data = resp.json()
        assert all(b["status"] in ("denied",) for b in data), f"Expected only denied, got: {data}"
        client.close()

    def test_bookings_limit(self, engine):
        """Respect limit parameter."""
        _register_agent(engine, "limit-agent", daily=100.0, monthly=1000.0)
        for i in range(10):
            engine.book("limit-agent", action=f"call-{i}", cost=0.01)
        from starlette.testclient import TestClient
        from src.api import app
        client = TestClient(app)
        resp = client.get("/dash/api/bookings?limit=5")
        data = resp.json()
        assert len(data) <= 5
        client.close()


class TestDashboardHTML:
    def test_dashboard_returns_html(self, engine):
        """GET /dash returns the dashboard HTML."""
        from starlette.testclient import TestClient
        from src.api import app
        client = TestClient(app)
        resp = client.get("/dash")
        assert resp.status_code == 200
        assert "<!DOCTYPE html>" in resp.text or "<html" in resp.text
        client.close()

    def test_dashboard_contains_key_elements(self, engine):
        """Dashboard HTML contains expected RGF elements."""
        from starlette.testclient import TestClient
        from src.api import app
        client = TestClient(app)
        resp = client.get("/dash")
        html = resp.text
        assert "RGF" in html
        assert "Dashboard" in html or "dashboard" in html.lower()
        client.close()


class TestDashboardAuth:
    def test_no_auth_required_when_pass_empty(self, engine):
        """Dashboard accessible without auth when DASH_PASS not set."""
        os.environ["RESGOV_DASH_PASS"] = ""
        from starlette.testclient import TestClient
        from src.api import app
        client = TestClient(app)
        resp = client.get("/dash/api/stats")
        assert resp.status_code == 200
        client.close()

    def test_auth_required_when_pass_set(self, engine):
        """Dashboard requires auth when DASH_PASS is set."""
        os.environ["RESGOV_DASH_PASS"] = "secret123"
        from starlette.testclient import TestClient
        from src.api import app
        client = TestClient(app)
        resp = client.get("/dash/api/stats")
        assert resp.status_code == 401
        client.close()
        os.environ["RESGOV_DASH_PASS"] = ""

    def test_valid_auth_succeeds(self, engine):
        """Valid Basic Auth credentials grant access."""
        os.environ["RESGOV_DASH_PASS"] = "secret123"
        import base64
        creds = base64.b64encode(b"admin:secret123").decode()
        from starlette.testclient import TestClient
        from src.api import app
        client = TestClient(app)
        resp = client.get("/dash/api/stats", headers={"Authorization": f"Basic {creds}"})
        assert resp.status_code == 200
        client.close()
        os.environ["RESGOV_DASH_PASS"] = ""
