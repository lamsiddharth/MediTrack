"""Appointment endpoints, including the double-booking rule."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from meditrack.db import get_session
from meditrack.models import Appointment, AppointmentStatus, Doctor, Patient, User
from meditrack.schemas import (
    AppointmentIn,
    AppointmentOut,
    AppointmentStatusIn,
    DoctorRef,
    PatientRef,
)
from meditrack.security import current_user

router = APIRouter(prefix="/api/appointments", tags=["appointments"])

# Treated as the length of a slot when checking for a clash.
SLOT_MINUTES = 20


def _out(a: Appointment) -> AppointmentOut:
    """Serialise an appointment, resolving the linked consultation id."""
    return AppointmentOut(
        id=a.id,
        scheduled_at=a.scheduled_at,
        reason=a.reason,
        status=a.status.value,
        patient=PatientRef(id=a.patient.id, full_name=a.patient.full_name, mrn=a.patient.mrn),
        doctor=DoctorRef(
            id=a.doctor.id,
            full_name=a.doctor.full_name,
            specialisation=a.doctor.specialisation,
        ),
        consultation_id=a.consultation.id if a.consultation else None,
    )


@router.get("", response_model=list[AppointmentOut])
async def list_appointments(
    on: str = "",
    status: str = "",
    _: User = Depends(current_user),
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

    if status and status in AppointmentStatus._value2member_map_:
        stmt = stmt.where(Appointment.status == AppointmentStatus(status))

    return [_out(a) for a in session.scalars(stmt.order_by(Appointment.scheduled_at)).all()]


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


@router.post("", response_model=AppointmentOut, status_code=201)
async def create_appointment(
    payload: AppointmentIn,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    if session.get(Patient, payload.patient_id) is None:
        raise HTTPException(status_code=404, detail="That patient no longer exists.")
    if session.get(Doctor, payload.doctor_id) is None:
        raise HTTPException(status_code=404, detail="That doctor no longer exists.")

    clash = _find_clash(session, payload.doctor_id, payload.scheduled_at)
    if clash is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"That doctor already has {clash.patient.full_name} booked at "
                f"{clash.scheduled_at.strftime('%H:%M on %d %b %Y')}. "
                f"Slots are {SLOT_MINUTES} minutes long — pick another time."
            ),
        )

    appointment = Appointment(
        patient_id=payload.patient_id,
        doctor_id=payload.doctor_id,
        scheduled_at=payload.scheduled_at,
        reason=(payload.reason or "").strip() or None,
    )
    session.add(appointment)
    session.commit()
    session.refresh(appointment)
    return _out(appointment)


@router.patch("/{appointment_id}/status", response_model=AppointmentOut)
async def set_status(
    appointment_id: int,
    payload: AppointmentStatusIn,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    appointment = session.get(Appointment, appointment_id)
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if payload.status not in AppointmentStatus._value2member_map_:
        raise HTTPException(status_code=422, detail=f"Unknown status: {payload.status}")

    appointment.status = AppointmentStatus(payload.status)
    session.commit()
    session.refresh(appointment)
    return _out(appointment)
