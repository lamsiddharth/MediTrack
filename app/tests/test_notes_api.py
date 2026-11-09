"""Session notes: storage drivers and the upload endpoint.

The S3 driver is exercised against moto, so these run with no AWS account.
"""

from __future__ import annotations

import io

import pytest

from meditrack import config
from meditrack.storage import LocalObjectStore, StorageError, safe_filename, validate_key

CONSULTATION = 1
NOTES_URL = f"/api/consultations/{CONSULTATION}/notes"


# ---------------------------------------------------------------------------
# Key and filename safety
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw, must_not_contain",
    [("../../etc/passwd", "/"), ("..\\..\\windows\\system32", "\\"), ("/abs/p.pdf", "/")],
)
def test_safe_filename_strips_path_components(raw, must_not_contain):
    cleaned = safe_filename(raw)
    assert must_not_contain not in cleaned
    assert ".." not in cleaned


def test_safe_filename_keeps_something_usable():
    assert safe_filename("Lab Report (Oct).pdf") == "Lab_Report_Oct_.pdf"
    assert safe_filename("") == "attachment"
    assert safe_filename("...") == "attachment"
    assert len(safe_filename("x" * 500 + ".pdf")) <= 120


@pytest.mark.parametrize("key", ["", "/leading", "a/../../b", "../x"])
def test_validate_key_rejects_traversal(key):
    with pytest.raises(StorageError):
        validate_key(key)


# ---------------------------------------------------------------------------
# Local driver
# ---------------------------------------------------------------------------
def test_local_store_round_trip(tmp_path):
    store = LocalObjectStore(tmp_path)
    store.put("a/b/c.txt", b"hello", "text/plain")
    assert store.get("a/b/c.txt") == b"hello"
    assert store.download_url("a/b/c.txt", "c.txt") is None
    store.delete("a/b/c.txt")
    with pytest.raises(StorageError):
        store.get("a/b/c.txt")


def test_local_store_refuses_to_escape_root(tmp_path):
    store = LocalObjectStore(tmp_path / "root")
    with pytest.raises(StorageError):
        store.put("../escaped.txt", b"x", "text/plain")


def test_local_store_delete_is_idempotent(tmp_path):
    LocalObjectStore(tmp_path).delete("never-existed.txt")


# ---------------------------------------------------------------------------
# S3 driver, against moto
# ---------------------------------------------------------------------------
@pytest.fixture
def s3_store():
    boto3 = pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")

    with moto.mock_aws():
        boto3.client("s3", region_name="ap-southeast-2").create_bucket(
            Bucket="test-bucket",
            CreateBucketConfiguration={"LocationConstraint": "ap-southeast-2"},
        )
        from meditrack.storage import S3ObjectStore

        yield S3ObjectStore(bucket="test-bucket", prefix="notes", region="ap-southeast-2")


def test_s3_store_round_trip(s3_store):
    s3_store.put("x/body.txt", b"clinical text", "text/plain")
    assert s3_store.get("x/body.txt") == b"clinical text"


def test_s3_store_applies_prefix(s3_store):
    import boto3

    s3_store.put("x/body.txt", b"data", "text/plain")
    keys = [
        o["Key"]
        for o in boto3.client("s3", region_name="ap-southeast-2")
        .list_objects_v2(Bucket="test-bucket")
        .get("Contents", [])
    ]
    assert keys == ["notes/x/body.txt"]


def test_s3_store_missing_key_raises(s3_store):
    with pytest.raises(StorageError):
        s3_store.get("absent.txt")


def test_s3_store_presigns_a_regional_url(s3_store):
    s3_store.put("x/report.pdf", b"%PDF-1.4", "application/pdf")
    url = s3_store.download_url("x/report.pdf", "report.pdf")
    assert url and url.startswith("https://")
    assert "X-Amz-Signature" in url
    # Must be the regional host: signed against the global endpoint, S3 answers
    # with a redirect and SigV4 then rejects the changed Host.
    assert "s3.ap-southeast-2.amazonaws.com" in url


def test_s3_store_delete(s3_store):
    s3_store.put("gone.txt", b"x", "text/plain")
    s3_store.delete("gone.txt")
    with pytest.raises(StorageError):
        s3_store.get("gone.txt")


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------
def test_notes_require_login(client):
    client.cookies.clear()
    r = client.post(NOTES_URL, data={"title": "x", "body": "y"})
    assert r.status_code == 401


def test_add_note_without_attachment(auth):
    r = auth.post(
        NOTES_URL,
        data={"title": "Telephone follow-up", "body": "Patient reports improvement."},
    )
    assert r.status_code == 201, r.text
    note = r.json()
    assert note["title"] == "Telephone follow-up"
    assert note["body"] == "Patient reports improvement."
    assert note["has_attachment"] is False
    assert note["author_name"]


def test_note_body_is_stored_as_an_object_not_in_the_row(auth):
    auth.post(NOTES_URL, data={"title": "Storage check", "body": "Body lives in storage."})

    from sqlalchemy import select

    from meditrack.db import SessionLocal
    from meditrack.models import SessionNote
    from meditrack.storage import get_store

    with SessionLocal() as session:
        note = session.scalars(
            select(SessionNote).where(SessionNote.title == "Storage check")
        ).one()

    assert note.body_key.endswith("/body.txt")
    assert note.storage_uid in note.body_key
    assert note.body_bytes == len(b"Body lives in storage.")
    assert get_store().get(note.body_key).decode() == "Body lives in storage."


def test_note_requires_title_and_body(auth):
    assert auth.post(NOTES_URL, data={"title": "  ", "body": "t"}).status_code == 422
    assert auth.post(NOTES_URL, data={"title": "T", "body": "  "}).status_code == 422


def test_notes_come_back_in_order_on_the_consultation(auth):
    for n in (1, 2, 3):
        auth.post(NOTES_URL, data={"title": f"Ordered {n}", "body": f"body {n}"})

    notes = auth.get(f"/api/consultations/{CONSULTATION}").json()["session_notes"]
    titles = [n["title"] for n in notes if n["title"].startswith("Ordered")]
    assert titles == ["Ordered 1", "Ordered 2", "Ordered 3"]


def test_note_on_unknown_consultation_is_404(auth):
    assert auth.post(
        "/api/consultations/999999/notes", data={"title": "x", "body": "y"}
    ).status_code == 404


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------
def test_add_note_with_attachment_and_download(auth):
    pdf = b"%PDF-1.4 fake lab report"
    r = auth.post(
        NOTES_URL,
        data={"title": "Lab results", "body": "Bloods attached."},
        files={"attachment": ("lab report.pdf", io.BytesIO(pdf), "application/pdf")},
    )
    assert r.status_code == 201, r.text
    note = r.json()
    assert note["has_attachment"] is True
    assert note["attachment_filename"] == "lab_report.pdf"
    assert note["attachment_size_label"]

    download = auth.get(f"{NOTES_URL}/{note['id']}/attachment")
    assert download.status_code == 200
    assert download.content == pdf


def test_oversized_attachment_rejected(auth, monkeypatch):
    monkeypatch.setattr(config, "MAX_ATTACHMENT_BYTES", 1024)
    r = auth.post(
        NOTES_URL,
        data={"title": "Too big", "body": "nope"},
        files={"attachment": ("big.pdf", io.BytesIO(b"x" * 2048), "application/pdf")},
    )
    assert r.status_code == 413
    assert "larger than" in r.json()["detail"]


def test_disallowed_attachment_type_rejected(auth):
    r = auth.post(
        NOTES_URL,
        data={"title": "Script", "body": "nope"},
        files={"attachment": ("evil.sh", io.BytesIO(b"#!/bin/sh"), "application/x-sh")},
    )
    assert r.status_code == 415
    assert "not accepted" in r.json()["detail"]


def test_empty_attachment_treated_as_none(auth):
    """A browser submits the file input even when nothing was chosen."""
    r = auth.post(
        NOTES_URL,
        data={"title": "No file", "body": "text only"},
        files={"attachment": ("", io.BytesIO(b""), "application/pdf")},
    )
    assert r.status_code == 201
    assert r.json()["has_attachment"] is False


def test_attachment_filename_cannot_escape_prefix(auth):
    r = auth.post(
        NOTES_URL,
        data={"title": "Traversal", "body": "check key"},
        files={"attachment": ("../../../../etc/passwd.txt", io.BytesIO(b"root:x"), "text/plain")},
    )
    assert r.status_code == 201

    from sqlalchemy import select

    from meditrack.db import SessionLocal
    from meditrack.models import SessionNote

    with SessionLocal() as session:
        note = session.scalars(
            select(SessionNote).where(SessionNote.title == "Traversal")
        ).one()

    assert ".." not in note.attachment_key
    assert note.attachment_key.startswith(f"consultations/{CONSULTATION}/notes/")


def test_missing_attachment_is_404(auth):
    note = auth.post(NOTES_URL, data={"title": "Textless", "body": "no file"}).json()
    assert auth.get(f"{NOTES_URL}/{note['id']}/attachment").status_code == 404
    assert auth.get(f"{NOTES_URL}/999999/attachment").status_code == 404


def test_attachment_scoped_to_its_consultation(auth):
    r = auth.post(
        NOTES_URL,
        data={"title": "Scoped", "body": "b"},
        files={"attachment": ("s.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
    )
    nid = r.json()["id"]
    assert auth.get(f"/api/consultations/{CONSULTATION}/notes/{nid}/attachment").status_code == 200
    assert auth.get(f"/api/consultations/2/notes/{nid}/attachment").status_code == 404


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------
def test_storage_failure_records_nothing(auth, monkeypatch):
    from meditrack import storage

    real = storage.get_store()

    class Failing:
        def put(self, key, data, content_type):
            raise StorageError("simulated outage")

        def get(self, key):
            return real.get(key)

        def delete(self, key):
            pass

        def download_url(self, key, filename):
            return None

    monkeypatch.setattr("meditrack.api.notes.get_store", lambda: Failing())

    r = auth.post(NOTES_URL, data={"title": "Should not persist", "body": "x"})
    assert r.status_code == 503
    assert "Could not save the note" in r.json()["detail"]

    from sqlalchemy import select

    from meditrack.db import SessionLocal
    from meditrack.models import SessionNote

    with SessionLocal() as session:
        found = session.scalars(
            select(SessionNote).where(SessionNote.title == "Should not persist")
        ).all()
    assert found == []


def test_unreadable_body_degrades_gracefully(auth):
    note = auth.post(NOTES_URL, data={"title": "Will vanish", "body": "temporary"}).json()

    from sqlalchemy import select

    from meditrack.db import SessionLocal
    from meditrack.models import SessionNote
    from meditrack.storage import get_store

    with SessionLocal() as session:
        row = session.scalars(
            select(SessionNote).where(SessionNote.title == "Will vanish")
        ).one()

    get_store().delete(row.body_key)

    detail = auth.get(f"/api/consultations/{CONSULTATION}")
    assert detail.status_code == 200
    vanished = next(n for n in detail.json()["session_notes"] if n["id"] == note["id"])
    assert vanished["unavailable"] is True
    assert vanished["body"] is None
