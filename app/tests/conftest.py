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
os.environ["STORAGE_BACKEND"] = "local"
os.environ["LOCAL_STORAGE_DIR"] = str(Path(_tmp) / "objects")

# Fake credentials, and no metadata lookups. Without these, any accidental
# real boto3 call would stall for a long time trying to reach the EC2
# instance-metadata endpoint instead of failing fast.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-2")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

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
        "/api/auth/login", json={"username": "admin", "password": "testpass123"}
    )
    assert response.status_code == 200, response.text
    return client
