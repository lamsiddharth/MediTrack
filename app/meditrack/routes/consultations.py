"""Recording what happened at a visit, and settling the bill."""

from __future__ import annotations

import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from meditrack import config
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
from meditrack.security import current_user
from meditrack.storage import StorageError, get_store
from meditrack.templating import templates

log = logging.getLogger("meditrack.consultations")

router = APIRouter(prefix="/consultations")


@router.get("")
async def list_consultations(
    request: Request,
    unpaid: str = "",
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    stmt = select(Consultation).options(
        joinedload(Consultation.patient), joinedload(Consultation.doctor)
    )
    only_unpaid = unpaid in {"1", "true", "yes"}
    if only_unpaid:
        stmt = stmt.where(Consultation.payment_status == PaymentStatus.unpaid)

    consultations = session.scalars(
        stmt.order_by(Consultation.visited_at.desc()).limit(100)
    ).all()

    return templates.TemplateResponse(
        request,
        "consultations/list.html",
        {"user": user, "consultations": consultations, "only_unpaid": only_unpaid},
    )


@router.get("/new")
async def new_consultation(
    request: Request,
    appointment_id: int | None = None,
    patient_id: int | None = None,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    appointment = None
    if appointment_id is not None:
        appointment = session.get(
            Appointment,
            appointment_id,
            options=[joinedload(Appointment.patient), joinedload(Appointment.doctor)],
        )
        if appointment is None:
            raise HTTPException(status_code=404)
        if appointment.consultation is not None:
            # Already recorded; send the user to it rather than letting them
            # create a second record against the same booking.
            return RedirectResponse(
                f"/consultations/{appointment.consultation.id}", status_code=303
            )

    return templates.TemplateResponse(
        request,
        "consultations/form.html",
        {
            "user": user,
            "appointment": appointment,
            "patients": session.scalars(select(Patient).order_by(Patient.full_name)).all(),
            "doctors": session.scalars(select(Doctor).order_by(Doctor.full_name)).all(),
            "preset_patient_id": patient_id or (appointment.patient_id if appointment else None),
            "preset_doctor_id": appointment.doctor_id if appointment else None,
            "preset_fee": float(appointment.doctor.consultation_fee) if appointment else None,
            "payment_statuses": list(PaymentStatus),
            "error": None,
            "form": {},
        },
    )


@router.post("/new")
async def create_consultation(
    request: Request,
    patient_id: int = Form(...),
    doctor_id: int = Form(...),
    diagnosis: str = Form(...),
    symptoms: str = Form(""),
    prescription: str = Form(""),
    notes: str = Form(""),
    follow_up_on: str = Form(""),
    fee: str = Form("0"),
    payment_status: str = Form(PaymentStatus.unpaid.value),
    appointment_id: str = Form(""),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    appointment = None
    if appointment_id:
        appointment = session.get(
            Appointment,
            int(appointment_id),
            options=[joinedload(Appointment.patient), joinedload(Appointment.doctor)],
        )

    def fail(message: str):
        return templates.TemplateResponse(
            request,
            "consultations/form.html",
            {
                "user": user,
                "appointment": appointment,
                "patients": session.scalars(select(Patient).order_by(Patient.full_name)).all(),
                "doctors": session.scalars(select(Doctor).order_by(Doctor.full_name)).all(),
                "preset_patient_id": patient_id,
                "preset_doctor_id": doctor_id,
                "preset_fee": None,
                "payment_statuses": list(PaymentStatus),
                "error": message,
                "form": {
                    "diagnosis": diagnosis,
                    "symptoms": symptoms,
                    "prescription": prescription,
                    "notes": notes,
                    "follow_up_on": follow_up_on,
                    "fee": fee,
                    "payment_status": payment_status,
                },
            },
            status_code=400,
        )

    if not diagnosis.strip():
        return fail("A diagnosis is required.")
    if session.get(Patient, patient_id) is None:
        return fail("That patient no longer exists.")
    if session.get(Doctor, doctor_id) is None:
        return fail("That doctor no longer exists.")

    try:
        fee_value = float(fee or 0)
    except ValueError:
        return fail("The fee must be a number.")
    if fee_value < 0:
        return fail("The fee cannot be negative.")

    follow_up: date | None = None
    if follow_up_on.strip():
        try:
            follow_up = date.fromisoformat(follow_up_on)
        except ValueError:
            return fail("Enter the follow-up date as YYYY-MM-DD.")

    if payment_status not in PaymentStatus._value2member_map_:
        return fail("Unknown payment status.")

    consultation = Consultation(
        patient_id=patient_id,
        doctor_id=doctor_id,
        appointment_id=appointment.id if appointment else None,
        visited_at=datetime.now(),
        symptoms=symptoms.strip() or None,
        diagnosis=diagnosis.strip(),
        prescription=prescription.strip() or None,
        notes=notes.strip() or None,
        follow_up_on=follow_up,
        fee=fee_value,
        payment_status=PaymentStatus(payment_status),
    )
    session.add(consultation)

    # Recording the visit is what marks the booking as done.
    if appointment is not None and appointment.status == AppointmentStatus.scheduled:
        appointment.status = AppointmentStatus.completed

    session.commit()
    return RedirectResponse(f"/consultations/{consultation.id}", status_code=303)


@router.get("/{consultation_id}")
async def consultation_detail(
    request: Request,
    consultation_id: int,
    noted: str = "",
    note_error: str = "",
    user: User = Depends(current_user),
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
        raise HTTPException(status_code=404)

    # Note bodies live in object storage, so each one is a fetch. There are
    # only ever a handful per session. A body that cannot be retrieved is
    # reported in place rather than failing the whole page.
    store = get_store()
    notes = []
    for note in consultation.session_notes:
        try:
            body = store.get(note.body_key).decode("utf-8", errors="replace")
            unavailable = False
        except StorageError:
            log.warning("note %s body missing from storage (%s)", note.id, note.body_key)
            body = None
            unavailable = True
        notes.append({"note": note, "body": body, "unavailable": unavailable})

    return templates.TemplateResponse(
        request,
        "consultations/detail.html",
        {
            "user": user,
            "consultation": consultation,
            "payment_statuses": list(PaymentStatus),
            "notes": notes,
            "noted": bool(noted),
            "note_error": note_error or None,
            "max_attachment_mb": config.MAX_ATTACHMENT_BYTES // (1024 * 1024),
            "allowed_extensions": ", ".join(sorted(config.ALLOWED_ATTACHMENT_TYPES.values())),
            "accept_attr": ",".join(sorted(config.ALLOWED_ATTACHMENT_TYPES)),
        },
    )


@router.post("/{consultation_id}/payment")
async def set_payment(
    consultation_id: int,
    payment_status: str = Form(...),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    consultation = session.get(Consultation, consultation_id)
    if consultation is None:
        raise HTTPException(status_code=404)
    if payment_status not in PaymentStatus._value2member_map_:
        raise HTTPException(status_code=400, detail="Unknown payment status")

    consultation.payment_status = PaymentStatus(payment_status)
    session.commit()
    return RedirectResponse(f"/consultations/{consultation_id}", status_code=303)
