"""Tests for dashboard endpoints: /dash, /dash/api/stats, /dash/api/agents, /dash/api/bookings."""
import os
import pytest
from unittest.mock import patch

from src.models import init_db
from src.engine import BudgetEngine, get_db as engine_get_db
from src.auth import init_api_keys_table
from src.middleware import get_db as middleware_get_db, close_db


@pytest.fixture(name="db_connection", scope="module")
def fixture_db_connection():
    """Use the module-isolated file DB from conftest.module_db."""
    db = middleware_get_db()
    yield db


@pytest.fixture(name="engine", scope="module")
def fixture_engine(db_connection):
    """BudgetEngine using the module-isolated test DB."""
    eng = BudgetEngine(db=db_connection)
    yield eng


@pytest.fixture(name="client", scope="module")
def fixture_client(db_connection):
    """TestClient with DB dependency overrides."""
    from src.api import app

    def override_get_db():
        return db_connection

    app.dependency_overrides[middleware_get_db] = override_get_db
    with patch("src.models.get_db", override_get_db), \
         patch("src.engine.get_db", override_get_db), \
         patch("src.middleware.get_db", override_get_db):
        from starlette.testclient import TestClient
        with TestClient(app) as client:
            yield client
    app.dependency_overrides.clear()


def _register_agent(engine, agent_id="test-agent", daily=10.0, monthly=100.0):
    engine.register_agent(agent_id=agent_id, name=f"Agent {agent_id}", daily_limit=daily, monthly_limit=monthly)


class TestDashboardStats:
    def test_stats_structure(self, engine, client):
        _register_agent(engine, "stats-agent-1")
        resp = client.get("/dash/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        assert "bookings" in data
        assert "costs" in data
        assert "metrics" in data
        assert data["agents"]["total"] >= 1

    def test_stats_costs(self, engine, client):
        _register_agent(engine, "cost-agent", daily=10.0, monthly=100.0)
        engine.book("cost-agent", action="test_call", cost=0.50)
        resp = client.get("/dash/api/stats")
        data = resp.json()
        assert data["bookings"]["total"] >= 1
        assert data["costs"]["total_spent"] >= 0.50


class TestDashboardAgents:
    def test_agents_list(self, engine, client):
        _register_agent(engine, "list-agent-1", daily=5.0, monthly=50.0)
        _register_agent(engine, "list-agent-2", daily=3.0, monthly=30.0)
        resp = client.get("/dash/api/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2
        agent_ids = [a["agent_id"] for a in data]
        assert "list-agent-1" in agent_ids
        assert "list-agent-2" in agent_ids

    def test_agent_budget_bars(self, engine, client):
        _register_agent(engine, "bar-agent", daily=10.0, monthly=100.0)
        engine.book("bar-agent", action="test", cost=2.00)
        resp = client.get("/dash/api/agents")
        data = resp.json()
        bar_agent = next(a for a in data if a["agent_id"] == "bar-agent")
        assert bar_agent["daily_limit"] == 10.0
        assert bar_agent["monthly_limit"] == 100.0


class TestDashboardBookings:
    def test_bookings_list(self, engine, client):
        _register_agent(engine, "book-agent", daily=10.0, monthly=100.0)
        engine.book("book-agent", action="chat", cost=0.10)
        engine.book("book-agent", action="compute", cost=0.20)
        resp = client.get("/dash/api/bookings")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2

    def test_bookings_filter_status(self, engine, client):
        _register_agent(engine, "filter-agent", daily=0.05, monthly=100.0)
        engine.book("filter-agent", action="ok", cost=0.01)
        engine.book("filter-agent", action="denied", cost=1.00)
        resp = client.get("/dash/api/bookings?status=denied")
        data = resp.json()
        assert all(b["status"] in ("denied",) for b in data), f"Expected only denied, got: {data}"

    def test_bookings_limit(self, engine, client):
        _register_agent(engine, "limit-agent", daily=100.0, monthly=1000.0)
        for i in range(10):
            engine.book("limit-agent", action=f"call-{i}", cost=0.01)
        resp = client.get("/dash/api/bookings?limit=5")
        data = resp.json()
        assert len(data) <= 5


class TestDashboardHTML:
    def test_dashboard_returns_html(self, engine, client):
        resp = client.get("/dash")
        assert resp.status_code == 200
        assert "<!DOCTYPE html>" in resp.text or "<html" in resp.text

    def test_dashboard_contains_key_elements(self, engine, client):
        resp = client.get("/dash")
        html = resp.text
        assert "RGF" in html
        assert "Dashboard" in html or "dashboard" in html.lower()
