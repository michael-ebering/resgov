
import pytest
import os
import time
from datetime import datetime, timedelta, timezone
from src.engine import BudgetEngine
from src.config import load_rgf_config
from fastapi.testclient import TestClient
from src.api import app, RGF_CONFIG
from src.models import init_db
import sqlite3

# Fixture for database connection
@pytest.fixture(name="db_connection")
def fixture_db_connection():
    # Use an in-memory database for testing
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()

# Fixture for BudgetEngine with test config
@pytest.fixture(name="budget_engine")
def fixture_budget_engine(db_connection):
    # Load test .rgf config
    RGF_CONFIG.update(load_rgf_config(".rgf"))
    init_db(db_connection)
    return BudgetEngine(rgf_config=RGF_CONFIG, db=db_connection)

    # Fixture for FastAPI TestClient
@pytest.fixture(name="test_client")
def fixture_test_client(db_connection):
    # Set admin token for testing admin endpoints
    os.environ["RESGOV_ADMIN_TOKEN"] = "test_admin_token"
    # Override get_db for testing to use in-memory db
    from src.middleware import get_db as original_get_db
    def override_get_db():
        return db_connection
    app.dependency_overrides[original_get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides = {} # Clear overrides
    del os.environ["RESGOV_ADMIN_TOKEN"] # Clean up env var

# Helper function to create an agent and make bookings
def setup_agent_and_bookings(engine: BudgetEngine, agent_id, daily_limit, monthly_limit, num_bookings, cost_per_booking, start_time_offset_seconds=0):
    engine.register_agent(agent_id=agent_id, name=f"{agent_id}-name",
                          daily_limit=daily_limit, monthly_limit=monthly_limit)
    
    current_time = datetime.now(timezone.utc) - timedelta(seconds=start_time_offset_seconds)
    for i in range(num_bookings):
        booking_time = current_time + timedelta(seconds=i)
        engine.book(agent_id=agent_id, cost=cost_per_booking, metadata={"timestamp": booking_time.isoformat()})
        time.sleep(0.1)


# --- Test Cases for BudgetEngine.get_budget_prediction ---
class TestBudgetPrediction:

    def test_prediction_constant_spend(self, budget_engine, db_connection):
        agent_id = "agent-constant"
        daily_limit = 100.0
        cost_per_booking = 1.0
        num_bookings = 10 # Total spent $10
        lookback_hours = 1 # Rate $10/hr

        setup_agent_and_bookings(budget_engine, agent_id, daily_limit, daily_limit * 30, num_bookings, cost_per_booking, start_time_offset_seconds=600)

        # Ensure enough time has passed for rate calculation
        time.sleep(1) 

        prediction = budget_engine.get_budget_prediction(agent_id, period="daily", lookback_hours=lookback_hours, db=db_connection)
        
        assert prediction["status"] == "ok"
        assert prediction["remaining_budget"] == 90.0
        # Rate should be approx 10.0 per hour (10 bookings in 0.1s total, 100 bookings in 1s total before sleep)
        # Assuming minimal sleep in setup_agent_and_bookings, it will be higher.
        # Let's check the remaining time
        assert prediction["remaining_time_seconds"] > 0
        assert prediction["prediction_timestamp"] is not None

    def test_prediction_no_recent_spend(self, budget_engine, db_connection):
        agent_id = "agent-no-spend"
        daily_limit = 50.0
        setup_agent_and_bookings(budget_engine, agent_id, daily_limit, daily_limit * 30, 0, 0.0)
        
        prediction = budget_engine.get_budget_prediction(agent_id, period="daily", lookback_hours=1, db=db_connection)
        
        assert prediction["status"] == "no_data"
        assert prediction["message"] == "Not enough recent spend data for prediction."

    def test_prediction_zero_rate(self, budget_engine, db_connection):
        agent_id = "agent-zero-rate"
        daily_limit = 50.0
        # Make one booking far in the past, then nothing.
        setup_agent_and_bookings(budget_engine, agent_id, daily_limit, daily_limit * 30, 1, 5.0, start_time_offset_seconds=3600*10) 
        
        prediction = budget_engine.get_budget_prediction(agent_id, period="daily", lookback_hours=1, db=db_connection)
        
        assert prediction["status"] == "ok"
        assert prediction["rate_usd_per_hour"] == 0.0
        assert prediction["remaining_time_seconds"] == float('inf')
        assert "until reset" in prediction["message"]

    def test_prediction_already_exhausted(self, budget_engine, db_connection):
        agent_id = "agent-exhausted"
        daily_limit = 10.0
        setup_agent_and_bookings(budget_engine, agent_id, daily_limit, daily_limit * 30, 1, 10.0) # Exactly exhaust budget
        
        prediction = budget_engine.get_budget_prediction(agent_id, period="daily", db=db_connection)
        
        assert prediction["status"] == "exhausted"
        assert "already exhausted" in prediction["message"]

    def test_prediction_agent_not_found(self, budget_engine, db_connection):
        agent_id = "non-existent-agent"
        prediction = budget_engine.get_budget_prediction(agent_id, period="daily", db=db_connection)
        
        assert prediction["status"] == "error"
        assert "not found" in prediction["message"]

# --- Test Cases for Prediction API Endpoint ---
class TestPredictionAPI:

    def test_api_prediction_success(self, test_client, budget_engine: BudgetEngine, db_connection):
        agent_id = "api-prediction-agent"
        daily_limit = 100.0
        cost_per_booking = 1.0
        num_bookings = 10
        lookback_hours = 1
        
        setup_agent_and_bookings(budget_engine, agent_id, daily_limit, daily_limit * 30, num_bookings, cost_per_booking, start_time_offset_seconds=600)

        # Generate a dummy API key for testing
        api_key_data = {"owner": "test", "name": "test-key", "scopes": "read,write", "org_id": "default"}
        response_key = test_client.post("/api/v1/admin/generate-key", 
                                       headers={"X-Admin-Token": "test_admin_token"},
                                       json=api_key_data)
        assert response_key.status_code == 200
        api_key = response_key.json()["api_key"]

        # Make the prediction API call
        response = test_client.get(f"/api/v1/agents/{agent_id}/prediction?period=daily&lookback_hours={lookback_hours}",
                                    headers={"X-API-Key": api_key})
        
        assert response.status_code == 200
        prediction = response.json()
        assert prediction["status"] == "ok"
        assert prediction["remaining_budget"] == 90.0
        assert prediction["rate_usd_per_hour"] > 0
        assert prediction["prediction_timestamp"] is not None
        assert prediction["remaining_time_seconds"] > 0

    def test_api_prediction_agent_not_found(self, test_client, db_connection):
        api_key_data = {"owner": "test", "name": "test-key", "scopes": "read,write", "org_id": "default"}
        response_key = test_client.post("/api/v1/admin/generate-key", 
                                       headers={"X-Admin-Token": "test_admin_token"},
                                       json=api_key_data)
        assert response_key.status_code == 200
        api_key = response_key.json()["api_key"]

        response = test_client.get("/api/v1/agents/non-existent/prediction", headers={"X-API-Key": api_key})
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_api_prediction_no_api_key(self, test_client):
        response = test_client.get("/api/v1/agents/some-agent/prediction")
        assert response.status_code == 401
        assert "Missing X-API-Key header" in response.json()["detail"]

