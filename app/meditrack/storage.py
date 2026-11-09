"""Object storage for session notes.

Note bodies and their attachments live in object storage rather than in the
database. Two interchangeable drivers:

  local  - a directory on disk. The default, so the app runs and the tests
           pass with no AWS account involved.
  s3     - an S3 bucket, which is what the deployed instance uses.

Keeping both behind one interface means nothing above this module knows or
cares which is in use.
"""

from __future__ import annotations

import logging
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Protocol

from meditrack import config

log = logging.getLogger("meditrack.storage")


class StorageError(Exception):
    """Raised when the backing store cannot satisfy a request."""


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def download_url(self, key: str, filename: str) -> str | None:
        """A direct URL for the client, or None if the app must stream it."""
        ...


# ---------------------------------------------------------------------------
# Key handling
# ---------------------------------------------------------------------------
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    """Reduce a user-supplied filename to something safe to put in a key.

    Strips directory components and anything outside a conservative character
    set, so an uploaded name like "../../etc/passwd" cannot escape its prefix.
    """
    name = unicodedata.normalize("NFKD", name or "")
    # Take the last path component under either separator before sanitising.
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE.sub("_", name).strip("._-")
    if not name:
        name = "attachment"
    return name[:120]


def validate_key(key: str) -> str:
    """Reject anything that could traverse outside the configured prefix."""
    if not key or key.startswith("/") or ".." in key.split("/"):
        raise StorageError(f"unsafe object key: {key!r}")
    return key


# ---------------------------------------------------------------------------
# Local driver
# ---------------------------------------------------------------------------
class LocalObjectStore:
    """Stores objects as files under a root directory."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        validate_key(key)
        path = (self.root / key).resolve()
        # Belt and braces: confirm the resolved path is still inside root.
        if not path.is_relative_to(self.root):
            raise StorageError(f"object key escapes the storage root: {key!r}")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise StorageError(f"object not found: {key}")
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    def download_url(self, key: str, filename: str) -> str | None:
        return None  # no direct URL; the app streams it

    def __repr__(self) -> str:
        return f"LocalObjectStore(root={self.root})"


# ---------------------------------------------------------------------------
# S3 driver
# ---------------------------------------------------------------------------
class S3ObjectStore:
    """Stores objects in an S3 bucket under an optional key prefix."""

    def __init__(self, bucket: str, prefix: str = "", region: str | None = None) -> None:
        # Imported here so the local driver needs no AWS libraries installed.
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=config.S3_ENDPOINT_URL or None,
            config=Config(
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=15,
                signature_version="s3v4",
                # Without this, presigned URLs are signed against the global
                # endpoint (bucket.s3.amazonaws.com). For a bucket outside
                # us-east-1 that endpoint answers with a 307 to the regional
                # host, and because SigV4 signs the host, following the
                # redirect invalidates the signature and the download fails.
                s3={"addressing_style": "virtual"},
            ),
        )

    def _full(self, key: str) -> str:
        validate_key(key)
        return f"{self.prefix}/{key}" if self.prefix else key

    def put(self, key: str, data: bytes, content_type: str) -> None:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            self._client.put_object(
                Bucket=self.bucket,
                Key=self._full(key),
                Body=data,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
        except (BotoCoreError, ClientError) as exc:
            log.exception("S3 put failed for %s", key)
            raise StorageError(f"could not store object: {exc}") from exc

    def get(self, key: str) -> bytes:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            response = self._client.get_object(Bucket=self.bucket, Key=self._full(key))
            return response["Body"].read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                raise StorageError(f"object not found: {key}") from exc
            log.exception("S3 get failed for %s", key)
            raise StorageError(f"could not read object: {exc}") from exc
        except BotoCoreError as exc:
            log.exception("S3 get failed for %s", key)
            raise StorageError(f"could not read object: {exc}") from exc

    def delete(self, key: str) -> None:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            self._client.delete_object(Bucket=self.bucket, Key=self._full(key))
        except (BotoCoreError, ClientError) as exc:
            log.warning("S3 delete failed for %s: %s", key, exc)

    def download_url(self, key: str, filename: str) -> str | None:
        """A short-lived presigned URL, so attachments are served by S3 rather
        than proxied through this single small instance. The bucket itself
        stays private."""
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return self._client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": self._full(key),
                    "ResponseContentDisposition": f'attachment; filename="{safe_filename(filename)}"',
                },
                ExpiresIn=config.S3_URL_TTL,
            )
        except (BotoCoreError, ClientError) as exc:
            log.warning("could not presign %s: %s", key, exc)
            return None  # fall back to streaming through the app

    def __repr__(self) -> str:
        return f"S3ObjectStore(bucket={self.bucket}, prefix={self.prefix!r})"


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------
_store: ObjectStore | None = None


def get_store() -> ObjectStore:
    """The configured store, built once."""
    global _store
    if _store is not None:
        return _store

    if config.STORAGE_BACKEND == "s3":
        if not config.S3_BUCKET:
            raise StorageError("STORAGE_BACKEND=s3 but S3_BUCKET is not set")
        _store = S3ObjectStore(
            bucket=config.S3_BUCKET, prefix=config.S3_PREFIX, region=config.AWS_REGION
        )
    elif config.STORAGE_BACKEND == "local":
        _store = LocalObjectStore(config.LOCAL_STORAGE_DIR)
    else:
        raise StorageError(
            f"unknown STORAGE_BACKEND {config.STORAGE_BACKEND!r}; use 'local' or 's3'"
        )

    log.info("object storage: %r", _store)
    return _store


def reset_store() -> None:
    """Drop the cached store. Used by tests."""
    global _store
    _store = None


def purge_local_storage() -> None:
    """Remove everything the local driver has written. Tests only."""
    if config.STORAGE_BACKEND == "local" and config.LOCAL_STORAGE_DIR.exists():
        shutil.rmtree(config.LOCAL_STORAGE_DIR)
