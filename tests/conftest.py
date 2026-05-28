"""Shared test fixtures and DB management for ResGov tests."""
import os
import tempfile
import pytest
import atexit

# Global test database — created once per session
_test_db_fd = None
_test_db_path = None
_cleanup_registered = False


def _cleanup_test_db():
    """Remove the test database file."""
    global _test_db_path
    if _test_db_path and os.path.exists(_test_db_path):
        try:
            os.unlink(_test_db_path)
        except OSError:
            pass
        _test_db_path = None


def get_test_db_path():
    """Get (and create if needed) the shared test database path."""
    global _test_db_fd, _test_db_path, _cleanup_registered
    if _test_db_path is None:
        _test_db_fd, _test_db_path = tempfile.mkstemp(suffix=".db")
        os.close(_test_db_fd)
        if not _cleanup_registered:
            atexit.register(_cleanup_test_db)
            _cleanup_registered = True
    return _test_db_path


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment variables once per session."""
    db_path = get_test_db_path()
    os.environ["RESGOV_DB_PATH"] = db_path
    os.environ["RESGOV_API_KEYS"] = ""
    # Dev mode — no admin token required (tests can override)
    if "RESGOV_ADMIN_TOKEN" not in os.environ:
        os.environ["RESGOV_ADMIN_TOKEN"] = "test-admin-token"

    from src.models import init_db
    from src.middleware import get_db, close_db

    db = get_db()
    init_db(db)
    from src.auth import init_api_keys_table
    init_api_keys_table()

    yield

    close_db()
    _cleanup_test_db()
