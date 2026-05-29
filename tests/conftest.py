"""Shared test fixtures and DB management for ResGov tests."""
import os
import tempfile
import pytest
import atexit
import glob

# Track all temp DB files for cleanup
_all_test_dbs = []


def _cleanup_all_dbs():
    """Remove all test database files."""
    for path in _all_test_dbs:
        if os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass
    _all_test_dbs.clear()


def get_test_db_path():
    """Get a unique temp DB path per test module."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    _all_test_dbs.append(path)
    return path


@pytest.fixture(scope="session", autouse=True)
def _global_setup():
    """Register cleanup at exit."""
    atexit.register(_cleanup_all_dbs)
    yield


@pytest.fixture(scope="module", autouse=True)
def module_db():
    """Each test module gets its own isolated temp SQLite file."""
    db_path = get_test_db_path()
    os.environ["RESGOV_DB_PATH"] = db_path
    os.environ["RESGOV_API_KEYS"] = ""
    if "RESGOV_ADMIN_TOKEN" not in os.environ:
        os.environ["RESGOV_ADMIN_TOKEN"] = "test-admin-token"

    from src.models import init_db
    from src.auth import init_api_keys_table
    from src.license import init_license_table
    from src.middleware import get_db, close_db

    close_db()
    db = get_db()
    init_db(db)
    init_api_keys_table()
    init_license_table()

    yield

    close_db()
