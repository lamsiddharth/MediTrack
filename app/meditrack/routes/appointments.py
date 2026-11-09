"""Booking and managing appointments."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from meditrack.db import get_session
from meditrack.models import Appointment, AppointmentStatus, Doctor, Patient, User
from meditrack.security import current_user
from meditrack.templating import templates

router = APIRouter(prefix="/appointments")

# Treated as the length of a slot when checking for a clash.
SLOT_MINUTES = 20


@router.get("")
async def list_appointments(
    request: Request,
    on: str = "",
    status: str = "",
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    try:
        day = date.fromisoformat(on) if on else date.today()
    except ValueError:
        day = date.today()

    day_start = datetime.combine(day, time.min)
    stmt = (
        select(Appointment)
        .options(joinedload(Appointment.patient), joinedload(Appointment.doctor))
        .where(
            Appointment.scheduled_at >= day_start,
            Appointment.scheduled_at < day_start + timedelta(days=1),
        )
    )

    selected_status = status if status in AppointmentStatus._value2member_map_ else ""
    if selected_status:
        stmt = stmt.where(Appointment.status == AppointmentStatus(selected_status))

    appointments = session.scalars(stmt.order_by(Appointment.scheduled_at)).all()

    return templates.TemplateResponse(
        request,
        "appointments/list.html",
        {
            "user": user,
            "appointments": appointments,
            "day": day,
            "prev_day": day - timedelta(days=1),
            "next_day": day + timedelta(days=1),
            "today": date.today(),
            "statuses": list(AppointmentStatus),
            "selected_status": selected_status,
        },
    )


def _form_context(session: Session, user: User, **extra):
    context = {
        "user": user,
        "patients": session.scalars(select(Patient).order_by(Patient.full_name)).all(),
        "doctors": session.scalars(select(Doctor).order_by(Doctor.full_name)).all(),
        "error": None,
        "preset_patient_id": None,
        "form": {},
    }
    context.update(extra)
    return context


@router.get("/new")
async def new_appointment(
    request: Request,
    patient_id: int | None = None,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request,
        "appointments/form.html",
        _form_context(session, user, preset_patient_id=patient_id),
    )


def _find_clash(
    session: Session, doctor_id: int, when: datetime, exclude_id: int | None = None
) -> Appointment | None:
    """Another live booking for the same doctor overlapping this slot.

    Cancellations and no-shows free the slot, so they are not clashes.
    """
    window_start = when - timedelta(minutes=SLOT_MINUTES - 1)
    window_end = when + timedelta(minutes=SLOT_MINUTES - 1)

    stmt = (
        select(Appointment)
        .options(joinedload(Appointment.patient))
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.scheduled_at >= window_start,
            Appointment.scheduled_at <= window_end,
            Appointment.status.in_([AppointmentStatus.scheduled, AppointmentStatus.completed]),
        )
    )
    if exclude_id is not None:
        stmt = stmt.where(Appointment.id != exclude_id)

    return session.scalars(stmt).first()


@router.post("/new")
async def create_appointment(
    request: Request,
    patient_id: int = Form(...),
    doctor_id: int = Form(...),
    scheduled_at: str = Form(...),
    reason: str = Form(""),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    def fail(message: str):
        return templates.TemplateResponse(
            request,
            "appointments/form.html",
            _form_context(
                session,
                user,
                error=message,
                preset_patient_id=patient_id,
                form={
                    "patient_id": patient_id,
                    "doctor_id": doctor_id,
                    "scheduled_at": scheduled_at,
                    "reason": reason,
                },
            ),
            status_code=400,
        )

    try:
        # The datetime-local input submits "YYYY-MM-DDTHH:MM".
        when = datetime.fromisoformat(scheduled_at)
    except ValueError:
        return fail("Enter a valid date and time.")

    if session.get(Patient, patient_id) is None:
        return fail("That patient no longer exists.")
    if session.get(Doctor, doctor_id) is None:
        return fail("That doctor no longer exists.")

    clash = _find_clash(session, doctor_id, when)
    if clash is not None:
        return fail(
            f"That doctor already has {clash.patient.full_name} booked at "
            f"{clash.scheduled_at.strftime('%H:%M on %d %b %Y')}. "
            f"Slots are {SLOT_MINUTES} minutes long — pick another time."
        )

    appointment = Appointment(
        patient_id=patient_id,
        doctor_id=doctor_id,
        scheduled_at=when,
        reason=reason.strip() or None,
    )
    session.add(appointment)
    session.commit()

    return RedirectResponse(
        f"/appointments?on={when.date().isoformat()}", status_code=303
    )


@router.post("/{appointment_id}/status")
async def set_status(
    appointment_id: int,
    status: str = Form(...),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    appointment = session.get(Appointment, appointment_id)
    if appointment is None:
        raise HTTPException(status_code=404)
    if status not in AppointmentStatus._value2member_map_:
        raise HTTPException(status_code=400, detail="Unknown status")

    appointment.status = AppointmentStatus(status)
    session.commit()

    return RedirectResponse(
        f"/appointments?on={appointment.scheduled_at.date().isoformat()}", status_code=303
    )
