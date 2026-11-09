"""Application configuration, read from the environment."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

APP_NAME = os.environ.get("APP_NAME", "MediTrack")

# Where the SQLite database lives. In the container this is a mounted volume,
# so the data survives the container being replaced.
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{DATA_DIR / 'meditrack.db'}"

# Signs the session cookie. Generated per-process if unset, which means
# restarting logs everyone out; set it explicitly in any real deployment.
SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_urlsafe(32)
SECRET_KEY_WAS_GENERATED = "SECRET_KEY" not in os.environ

# Session lifetime in seconds.
SESSION_MAX_AGE = int(os.environ.get("SESSION_MAX_AGE", 8 * 60 * 60))

# The single seeded account. Change the password after first login.
SEED_USERNAME = os.environ.get("SEED_USERNAME", "admin")
SEED_PASSWORD = os.environ.get("SEED_PASSWORD", "admin123")
SEED_FULL_NAME = os.environ.get("SEED_FULL_NAME", "Dr. A. Menon")

# Whether to populate demo records on an empty database.
SEED_DEMO_DATA = os.environ.get("SEED_DEMO_DATA", "true").lower() in {"1", "true", "yes"}
