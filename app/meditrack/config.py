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

# --- Object storage for session notes -------------------------------------
# "local" keeps objects on disk so the app runs with no AWS account.
# "s3" is what the deployed instance uses.
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local").strip().lower()

LOCAL_STORAGE_DIR = Path(
    os.environ.get("LOCAL_STORAGE_DIR", str(DATA_DIR / "objects"))
).resolve()

S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_PREFIX = os.environ.get("S3_PREFIX", "session-notes")
AWS_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or None

# Override the S3 endpoint, for a non-AWS S3-compatible store (MinIO, etc).
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", "")

# Lifetime of a presigned attachment URL, in seconds.
S3_URL_TTL = int(os.environ.get("S3_URL_TTL", 300))

# Attachment limits. Enforced before anything is sent to storage.
MAX_ATTACHMENT_BYTES = int(os.environ.get("MAX_ATTACHMENT_BYTES", 10 * 1024 * 1024))

ALLOWED_ATTACHMENT_TYPES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "text/plain": ".txt",
}
