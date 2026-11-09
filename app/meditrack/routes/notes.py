"""Session notes: append-only progress notes held in object storage."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session, joinedload

# Starlette's class, not fastapi.UploadFile: request.form() yields the former,
# and fastapi.UploadFile is a subclass, so isinstance against it never matches.
from starlette.datastructures import UploadFile

from meditrack import config
from meditrack.db import get_session
from meditrack.models import Consultation, SessionNote, User
from meditrack.security import current_user
from meditrack.storage import StorageError, get_store, safe_filename

log = logging.getLogger("meditrack.notes")

router = APIRouter(prefix="/consultations/{consultation_id}/notes")


def _load_consultation(session: Session, consultation_id: int) -> Consultation:
    consultation = session.get(
        Consultation,
        consultation_id,
        options=[joinedload(Consultation.patient), joinedload(Consultation.doctor)],
    )
    if consultation is None:
        raise HTTPException(status_code=404)
    return consultation


def _body_key(consultation_id: int, uid: str) -> str:
    return f"consultations/{consultation_id}/notes/{uid}/body.txt"


def _attachment_key(consultation_id: int, uid: str, filename: str) -> str:
    return f"consultations/{consultation_id}/notes/{uid}/attachment/{filename}"


@router.post("")
async def add_note(
    consultation_id: int,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    consultation = _load_consultation(session, consultation_id)
    store = get_store()

    def back(error: str | None = None):
        suffix = f"?note_error={error}" if error else "?noted=1"
        return RedirectResponse(f"/consultations/{consultation_id}{suffix}", status_code=303)

    # The form is read directly rather than through typed parameters. A browser
    # always submits the file input, even when nothing was chosen, as a part
    # with an empty filename; declaring it as UploadFile makes that a 422 and
    # breaks every note saved without an attachment.
    form = await request.form()

    title_clean = str(form.get("title") or "").strip()
    body_clean = str(form.get("body") or "").strip()
    if not title_clean:
        return back("A note needs a title.")
    if not body_clean:
        return back("A note needs some text.")

    # --- read and validate the attachment before writing anything ---------
    attachment_bytes: bytes | None = None
    attachment_name: str | None = None
    attachment_type: str | None = None

    upload = form.get("attachment")
    if isinstance(upload, UploadFile) and upload.filename:
        attachment_bytes = await upload.read()
        if len(attachment_bytes) == 0:
            attachment_bytes = None
        else:
            if len(attachment_bytes) > config.MAX_ATTACHMENT_BYTES:
                limit_mb = config.MAX_ATTACHMENT_BYTES / (1024 * 1024)
                return back(f"That file is larger than the {limit_mb:.0f} MB limit.")

            attachment_type = (upload.content_type or "").split(";")[0].strip().lower()
            if attachment_type not in config.ALLOWED_ATTACHMENT_TYPES:
                allowed = ", ".join(sorted(config.ALLOWED_ATTACHMENT_TYPES.values()))
                return back(f"That file type is not accepted. Allowed: {allowed}.")

            attachment_name = safe_filename(upload.filename)

    # --- write to object storage, then record it --------------------------
    uid = uuid.uuid4().hex
    body_encoded = body_clean.encode("utf-8")
    body_key = _body_key(consultation_id, uid)
    written: list[str] = []

    try:
        store.put(body_key, body_encoded, "text/plain; charset=utf-8")
        written.append(body_key)

        attachment_key = None
        if attachment_bytes is not None:
            attachment_key = _attachment_key(consultation_id, uid, attachment_name)
            store.put(attachment_key, attachment_bytes, attachment_type)
            written.append(attachment_key)
    except StorageError as exc:
        log.error("storing note for consultation %s failed: %s", consultation_id, exc)
        for key in written:
            store.delete(key)
        return back("Could not save the note to storage. Nothing was recorded.")

    note = SessionNote(
        consultation_id=consultation.id,
        author_id=user.id,
        title=title_clean,
        storage_uid=uid,
        body_key=body_key,
        body_bytes=len(body_encoded),
        attachment_key=attachment_key,
        attachment_filename=attachment_name,
        attachment_content_type=attachment_type,
        attachment_bytes=len(attachment_bytes) if attachment_bytes is not None else None,
    )
    session.add(note)

    try:
        session.commit()
    except Exception:
        # The objects are already in storage; remove them so a failed insert
        # does not leave unreferenced data behind.
        session.rollback()
        for key in written:
            store.delete(key)
        raise

    return back()


@router.get("/{note_id}/attachment")
async def download_attachment(
    consultation_id: int,
    note_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    note = session.get(SessionNote, note_id)
    if note is None or note.consultation_id != consultation_id or not note.attachment_key:
        raise HTTPException(status_code=404)

    store = get_store()
    filename = note.attachment_filename or "attachment"

    # With S3, hand the client a short-lived presigned URL so the download is
    # served by S3 rather than proxied through this one small instance. The
    # bucket stays private either way.
    url = store.download_url(note.attachment_key, filename)
    if url:
        return RedirectResponse(url, status_code=303)

    try:
        data = store.get(note.attachment_key)
    except StorageError:
        raise HTTPException(status_code=404)

    return Response(
        content=data,
        media_type=note.attachment_content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
