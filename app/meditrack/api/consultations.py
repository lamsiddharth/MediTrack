"""Consultation endpoints: the clinical record and its billing."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from meditrack.db import get_session
from meditrack.models import (
    Appointment,
    AppointmentStatus,
    Consultation,
    Doctor,
    Patient,
    PaymentStatus,
    SessionNote,
    User,
)
from meditrack.schemas import (
    ConsultationDetailOut,
    ConsultationIn,
    ConsultationOut,
    PaymentStatusIn,
    SessionNoteOut,
)
from meditrack.security import current_user
from meditrack.storage import StorageError, get_store

log = logging.getLogger("meditrack.api.consultations")

router = APIRouter(prefix="/api/consultations", tags=["consultations"])


@router.get("", response_model=list[ConsultationOut])
async def list_consultations(
    unpaid: bool = False,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    stmt = select(Consultation).options(
        joinedload(Consultation.patient), joinedload(Consultation.doctor)
    )
    if unpaid:
        stmt = stmt.where(Consultation.payment_status == PaymentStatus.unpaid)

    return session.scalars(stmt.order_by(Consultation.visited_at.desc()).limit(200)).all()


@router.post("", response_model=ConsultationOut, status_code=201)
async def create_consultation(
    payload: ConsultationIn,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    if session.get(Patient, payload.patient_id) is None:
        raise HTTPException(status_code=404, detail="That patient no longer exists.")
    if session.get(Doctor, payload.doctor_id) is None:
        raise HTTPException(status_code=404, detail="That doctor no longer exists.")
    if payload.payment_status not in PaymentStatus._value2member_map_:
        raise HTTPException(
            status_code=422, detail=f"Unknown payment status: {payload.payment_status}"
        )

    appointment = None
    if payload.appointment_id is not None:
        appointment = session.get(Appointment, payload.appointment_id)
        if appointment is None:
            raise HTTPException(status_code=404, detail="Appointment not found")
        if appointment.consultation is not None:
            raise HTTPException(
                status_code=409,
                detail="This appointment already has a consultation recorded.",
            )

    consultation = Consultation(
        patient_id=payload.patient_id,
        doctor_id=payload.doctor_id,
        appointment_id=appointment.id if appointment else None,
        visited_at=datetime.now(),
        symptoms=(payload.symptoms or "").strip() or None,
        diagnosis=payload.diagnosis.strip(),
        prescription=(payload.prescription or "").strip() or None,
        notes=(payload.notes or "").strip() or None,
        follow_up_on=payload.follow_up_on,
        fee=payload.fee,
        payment_status=PaymentStatus(payload.payment_status),
    )
    session.add(consultation)

    # Recording the visit is what marks the booking as done.
    if appointment is not None and appointment.status == AppointmentStatus.scheduled:
        appointment.status = AppointmentStatus.completed

    session.commit()
    session.refresh(consultation)
    return consultation


@router.get("/{consultation_id}", response_model=ConsultationDetailOut)
async def get_consultation(
    consultation_id: int,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    consultation = session.get(
        Consultation,
        consultation_id,
        options=[
            joinedload(Consultation.patient),
            joinedload(Consultation.doctor),
            joinedload(Consultation.session_notes).joinedload(SessionNote.author),
        ],
    )
    if consultation is None:
        raise HTTPException(status_code=404, detail="Consultation not found")

    # Note bodies live in object storage, so each is a fetch. There are only
    # ever a handful per session. A body that cannot be retrieved is reported
    # as unavailable rather than failing the whole response.
    store = get_store()
    notes: list[SessionNoteOut] = []
    for note in consultation.session_notes:
        try:
            body = store.get(note.body_key).decode("utf-8", errors="replace")
            unavailable = False
        except StorageError:
            log.warning("note %s body missing from storage (%s)", note.id, note.body_key)
            body, unavailable = None, True

        notes.append(
            SessionNoteOut(
                id=note.id,
                title=note.title,
                created_at=note.created_at,
                author_name=note.author.full_name,
                body=body,
                unavailable=unavailable,
                attachment_filename=note.attachment_filename,
                attachment_size_label=note.attachment_size_label if note.has_attachment else None,
                has_attachment=note.has_attachment,
            )
        )

    base = ConsultationOut.model_validate(consultation)
    return ConsultationDetailOut(
        **base.model_dump(),
        patient_allergies=consultation.patient.allergies,
        session_notes=notes,
    )


@router.patch("/{consultation_id}/payment", response_model=ConsultationOut)
async def set_payment(
    consultation_id: int,
    payload: PaymentStatusIn,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    consultation = session.get(Consultation, consultation_id)
    if consultation is None:
        raise HTTPException(status_code=404, detail="Consultation not found")
    if payload.payment_status not in PaymentStatus._value2member_map_:
        raise HTTPException(
            status_code=422, detail=f"Unknown payment status: {payload.payment_status}"
        )

    consultation.payment_status = PaymentStatus(payload.payment_status)
    session.commit()
    session.refresh(consultation)
    return consultation
