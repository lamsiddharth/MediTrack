from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Point the app at a throwaway database before anything imports config.
_tmp = tempfile.mkdtemp(prefix="meditrack-test-")
os.environ["DATA_DIR"] = _tmp
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp) / 'test.db'}"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["SEED_PASSWORD"] = "testpass123"
os.environ["SEED_DEMO_DATA"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from meditrack.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    # The context manager runs lifespan, which creates the schema and seeds.
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth(client):
    """A client already signed in as the seeded account."""
    client.cookies.clear()
    response = client.post(
        "/login",
        data={"username": "admin", "password": "testpass123", "next": "/"},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return client
