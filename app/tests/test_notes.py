"""Session notes: storage drivers, the upload path, and its validation.

The S3 driver is exercised against moto, so these run with no AWS account.
"""

from __future__ import annotations

import io

import pytest

from meditrack import config
from meditrack.storage import (
    LocalObjectStore,
    StorageError,
    safe_filename,
    validate_key,
)

CONSULTATION = 1
NOTES_URL = f"/consultations/{CONSULTATION}/notes"


# ---------------------------------------------------------------------------
# Key and filename safety
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw, expected_not",
    [
        ("../../etc/passwd", "/"),
        ("..\\..\\windows\\system32", "\\"),
        ("/absolute/path.pdf", "/"),
    ],
)
def test_safe_filename_strips_path_components(raw, expected_not):
    cleaned = safe_filename(raw)
    assert expected_not not in cleaned
    assert ".." not in cleaned


def test_safe_filename_keeps_something_usable():
    assert safe_filename("Lab Report (Oct).pdf") == "Lab_Report_Oct_.pdf"
    assert safe_filename("") == "attachment"
    assert safe_filename("...") == "attachment"


def test_safe_filename_is_length_capped():
    assert len(safe_filename("x" * 500 + ".pdf")) <= 120


@pytest.mark.parametrize("key", ["", "/leading", "a/../../b", "../x"])
def test_validate_key_rejects_traversal(key):
    with pytest.raises(StorageError):
        validate_key(key)


def test_validate_key_allows_normal_keys():
    assert validate_key("consultations/1/notes/abc/body.txt")


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


def test_local_store_missing_object_raises(tmp_path):
    with pytest.raises(StorageError):
        LocalObjectStore(tmp_path).get("nope.txt")


def test_local_store_refuses_to_escape_root(tmp_path):
    store = LocalObjectStore(tmp_path / "root")
    with pytest.raises(StorageError):
        store.put("../escaped.txt", b"x", "text/plain")


def test_local_store_delete_is_idempotent(tmp_path):
    LocalObjectStore(tmp_path).delete("never-existed.txt")  # must not raise


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


def test_s3_store_missing_key_raises_storage_error(s3_store):
    with pytest.raises(StorageError):
        s3_store.get("absent.txt")


def test_s3_store_presigns_a_download_url(s3_store):
    s3_store.put("x/report.pdf", b"%PDF-1.4", "application/pdf")
    url = s3_store.download_url("x/report.pdf", "report.pdf")
    assert url and url.startswith("https://")
    assert "X-Amz-Signature" in url
    # The filename is pushed into the response headers by the signed URL.
    assert "report.pdf" in url


def test_s3_store_delete_removes_object(s3_store):
    s3_store.put("gone.txt", b"x", "text/plain")
    s3_store.delete("gone.txt")
    with pytest.raises(StorageError):
        s3_store.get("gone.txt")


# ---------------------------------------------------------------------------
# Adding notes through the app
# ---------------------------------------------------------------------------
def test_notes_require_login(client):
    client.cookies.clear()
    response = client.post(NOTES_URL, data={"title": "x", "body": "y"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_add_note_without_attachment(auth):
    response = auth.post(
        NOTES_URL,
        data={"title": "Telephone follow-up", "body": "Patient reports improvement."},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Note added." in response.text
    assert "Telephone follow-up" in response.text
    assert "Patient reports improvement." in response.text


def test_note_body_is_stored_as_an_object_not_in_the_row(auth):
    auth.post(
        NOTES_URL,
        data={"title": "Storage check", "body": "This body lives in object storage."},
        follow_redirects=True,
    )

    from sqlalchemy import select

    from meditrack.db import SessionLocal
    from meditrack.models import SessionNote
    from meditrack.storage import get_store

    with SessionLocal() as session:
        note = session.scalars(
            select(SessionNote).where(SessionNote.title == "Storage check")
        ).one()

    # The row holds a key, and the text is only retrievable from the store.
    assert note.body_key.endswith("/body.txt")
    assert note.storage_uid in note.body_key
    assert note.body_bytes == len(b"This body lives in object storage.")
    assert get_store().get(note.body_key).decode() == "This body lives in object storage."


def test_note_requires_title_and_body(auth):
    blank_title = auth.post(
        NOTES_URL, data={"title": "   ", "body": "text"}, follow_redirects=True
    )
    assert "needs a title" in blank_title.text

    blank_body = auth.post(
        NOTES_URL, data={"title": "Title", "body": "   "}, follow_redirects=True
    )
    assert "needs some text" in blank_body.text


def test_notes_appear_in_chronological_order(auth):
    for n in (1, 2, 3):
        auth.post(
            NOTES_URL,
            data={"title": f"Ordered note {n}", "body": f"body {n}"},
            follow_redirects=True,
        )

    page = auth.get(f"/consultations/{CONSULTATION}").text
    positions = [page.index(f"Ordered note {n}") for n in (1, 2, 3)]
    assert positions == sorted(positions)


def test_note_on_unknown_consultation_is_404(auth):
    response = auth.post(
        "/consultations/999999/notes", data={"title": "x", "body": "y"}
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------
def test_add_note_with_attachment_then_download_it(auth):
    pdf = b"%PDF-1.4 fake lab report bytes"
    response = auth.post(
        NOTES_URL,
        data={"title": "Lab results", "body": "Bloods attached."},
        files={"attachment": ("lab report.pdf", io.BytesIO(pdf), "application/pdf")},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Note added." in response.text
    # Sanitised filename is shown.
    assert "lab_report.pdf" in response.text

    from sqlalchemy import select

    from meditrack.db import SessionLocal
    from meditrack.models import SessionNote

    with SessionLocal() as session:
        note = session.scalars(
            select(SessionNote).where(SessionNote.title == "Lab results")
        ).one()

    assert note.attachment_content_type == "application/pdf"
    assert note.attachment_bytes == len(pdf)
    assert note.attachment_filename == "lab_report.pdf"

    download = auth.get(f"{NOTES_URL}/{note.id}/attachment")
    assert download.status_code == 200
    assert download.content == pdf


def test_attachment_over_the_size_limit_is_rejected(auth, monkeypatch):
    monkeypatch.setattr(config, "MAX_ATTACHMENT_BYTES", 1024)
    oversized = b"x" * 2048

    response = auth.post(
        NOTES_URL,
        data={"title": "Too big", "body": "nope"},
        files={"attachment": ("big.pdf", io.BytesIO(oversized), "application/pdf")},
        follow_redirects=True,
    )
    assert "larger than" in response.text
    assert "Too big" not in response.text.split("Session notes")[-1].split("Add a note")[0]


def test_disallowed_attachment_type_is_rejected(auth):
    response = auth.post(
        NOTES_URL,
        data={"title": "Executable", "body": "nope"},
        files={"attachment": ("evil.sh", io.BytesIO(b"#!/bin/sh\nrm -rf /"),
                              "application/x-sh")},
        follow_redirects=True,
    )
    assert "not accepted" in response.text


def test_empty_attachment_is_treated_as_no_attachment(auth):
    response = auth.post(
        NOTES_URL,
        data={"title": "No file really", "body": "text only"},
        files={"attachment": ("", io.BytesIO(b""), "application/pdf")},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Note added." in response.text


def test_attachment_filename_cannot_escape_its_prefix(auth):
    response = auth.post(
        NOTES_URL,
        data={"title": "Traversal attempt", "body": "check the key"},
        files={"attachment": ("../../../../etc/passwd.txt",
                              io.BytesIO(b"root:x:0:0"), "text/plain")},
        follow_redirects=True,
    )
    assert response.status_code == 200

    from sqlalchemy import select

    from meditrack.db import SessionLocal
    from meditrack.models import SessionNote

    with SessionLocal() as session:
        note = session.scalars(
            select(SessionNote).where(SessionNote.title == "Traversal attempt")
        ).one()

    assert ".." not in note.attachment_key
    assert note.attachment_key.startswith(f"consultations/{CONSULTATION}/notes/")


def test_download_of_missing_attachment_is_404(auth):
    # A note with no attachment at all.
    auth.post(NOTES_URL, data={"title": "Textless", "body": "no file"},
              follow_redirects=True)

    from sqlalchemy import select

    from meditrack.db import SessionLocal
    from meditrack.models import SessionNote

    with SessionLocal() as session:
        note = session.scalars(
            select(SessionNote).where(SessionNote.title == "Textless")
        ).one()

    assert auth.get(f"{NOTES_URL}/{note.id}/attachment").status_code == 404
    assert auth.get(f"{NOTES_URL}/999999/attachment").status_code == 404


def test_attachment_cannot_be_fetched_via_another_consultation(auth):
    """The note id must belong to the consultation in the path."""
    pdf = b"%PDF-1.4 x"
    auth.post(
        NOTES_URL,
        data={"title": "Scoped", "body": "b"},
        files={"attachment": ("s.pdf", io.BytesIO(pdf), "application/pdf")},
        follow_redirects=True,
    )

    from sqlalchemy import select

    from meditrack.db import SessionLocal
    from meditrack.models import SessionNote

    with SessionLocal() as session:
        note = session.scalars(
            select(SessionNote).where(SessionNote.title == "Scoped")
        ).one()

    # Correct consultation works, a different one does not.
    assert auth.get(f"/consultations/{CONSULTATION}/notes/{note.id}/attachment").status_code == 200
    assert auth.get(f"/consultations/2/notes/{note.id}/attachment").status_code == 404


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------
def test_storage_failure_records_nothing(auth, monkeypatch):
    """If the object store rejects the write, no row should be left behind."""
    from meditrack import storage

    real_store = storage.get_store()

    class Failing:
        def put(self, key, data, content_type):
            raise StorageError("simulated outage")

        def get(self, key):
            return real_store.get(key)

        def delete(self, key):
            pass

        def download_url(self, key, filename):
            return None

    monkeypatch.setattr(storage, "get_store", lambda: Failing())
    monkeypatch.setattr("meditrack.routes.notes.get_store", lambda: Failing())

    response = auth.post(
        NOTES_URL,
        data={"title": "Should not persist", "body": "x"},
        follow_redirects=True,
    )
    assert "Could not save the note" in response.text

    from sqlalchemy import select

    from meditrack.db import SessionLocal
    from meditrack.models import SessionNote

    with SessionLocal() as session:
        found = session.scalars(
            select(SessionNote).where(SessionNote.title == "Should not persist")
        ).all()
    assert found == []


def test_unreadable_body_degrades_gracefully(auth):
    """A note whose object has gone missing must not break the whole page."""
    auth.post(NOTES_URL, data={"title": "Will vanish", "body": "temporary"},
              follow_redirects=True)

    from sqlalchemy import select

    from meditrack.db import SessionLocal
    from meditrack.models import SessionNote
    from meditrack.storage import get_store

    with SessionLocal() as session:
        note = session.scalars(
            select(SessionNote).where(SessionNote.title == "Will vanish")
        ).one()

    get_store().delete(note.body_key)

    page = auth.get(f"/consultations/{CONSULTATION}")
    assert page.status_code == 200
    assert "could not be read from storage" in page.text
    # The rest of the record still renders.
    assert "Session notes" in page.text
