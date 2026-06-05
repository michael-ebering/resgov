"""Tests for dashboard prediction endpoints: /dash/api/predictions, /dash/api/agent/{id}/prediction."""
import os
import pytest
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from src.models import init_db
from src.engine import BudgetEngine
from src.auth import init_api_keys_table
from src.middleware import get_db as middleware_get_db, close_db


@pytest.fixture(name="db_connection", scope="module")
def fixture_db_connection():
    db = middleware_get_db()
    yield db


@pytest.fixture(name="engine", scope="module")
def fixture_engine(db_connection):
    eng = BudgetEngine(db=db_connection)
    yield eng


@pytest.fixture(name="client", scope="module")
def fixture_client(db_connection):
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


def _register_and_spend(engine, agent_id, daily=100.0, monthly=1000.0, bookings=None):
    engine.register_agent(agent_id=agent_id, name=f"Agent {agent_id}",
                          daily_limit=daily, monthly_limit=monthly)
    if bookings:
        for cost in bookings:
            engine.book(agent_id, action="test", cost=cost)


class TestDashboardPredictions:
    def test_predictions_all_agents(self, engine, client):
        _register_and_spend(engine, "pred-all-1", daily=100.0, bookings=[1.0, 2.0, 3.0])
        _register_and_spend(engine, "pred-all-2", daily=50.0, bookings=[10.0])
        resp = client.get("/dash/api/predictions?period=daily&lookback_hours=6")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 2
        ids = [d["agent_id"] for d in data]
        assert "pred-all-1" in ids
        assert "pred-all-2" in ids

    def test_predictions_structure(self, engine, client):
        _register_and_spend(engine, "pred-struct", daily=100.0, bookings=[5.0])
        resp = client.get("/dash/api/predictions?period=daily")
        assert resp.status_code == 200
        data = resp.json()
        agent = next(d for d in data if d["agent_id"] == "pred-struct")
        assert "status" in agent
        assert "remaining_budget" in agent
        assert "rate_usd_per_hour" in agent
        assert "prediction_timestamp" in agent
        assert "remaining_time_seconds" in agent
        assert agent["status"] == "ok"

    def test_predictions_exhausted(self, engine, client):
        _register_and_spend(engine, "pred-exhaust", daily=10.0, bookings=[10.0])
        resp = client.get("/dash/api/predictions?period=daily")
        assert resp.status_code == 200
        data = resp.json()
        agent = next(d for d in data if d["agent_id"] == "pred-exhaust")
        assert agent["status"] == "exhausted"

    def test_predictions_no_data(self, engine, client):
        engine.register_agent(agent_id="pred-nodata", name="No Data", daily_limit=50.0, monthly_limit=500.0)
        resp = client.get("/dash/api/predictions?period=daily")
        assert resp.status_code == 200
        data = resp.json()
        agent = next(d for d in data if d["agent_id"] == "pred-nodata")
        assert agent["status"] == "no_data"

    def test_predictions_monthly_period(self, engine, client):
        _register_and_spend(engine, "pred-monthly", daily=100.0, monthly=1000.0, bookings=[50.0])
        resp = client.get("/dash/api/predictions?period=monthly&lookback_hours=6")
        assert resp.status_code == 200
        data = resp.json()
        agent = next(d for d in data if d["agent_id"] == "pred-monthly")
        assert agent["status"] in ("ok", "no_data")

    def test_predictions_empty_agents(self, client):
        resp = client.get("/dash/api/predictions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestDashboardAgentPrediction:
    def test_single_agent_prediction(self, engine, client):
        _register_and_spend(engine, "pred-single", daily=100.0, bookings=[5.0])
        resp = client.get("/dash/api/agent/pred-single/prediction?period=daily")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["remaining_budget"] == 95.0

    def test_single_agent_not_found(self, client):
        resp = client.get("/dash/api/agent/nonexistent/prediction")
        assert resp.status_code == 404

    def test_single_agent_exhausted(self, engine, client):
        _register_and_spend(engine, "pred-single-exh", daily=5.0, bookings=[5.0])
        resp = client.get("/dash/api/agent/pred-single-exh/prediction?period=daily")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "exhausted"
