"""Dashboard endpoint and client metadata."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from meditrack import config
from meditrack.api.appointments import SLOT_MINUTES, _out
from meditrack.db import get_session
from meditrack.models import (
    Appointment,
    AppointmentStatus,
    Consultation,
    Doctor,
    Patient,
    PaymentStatus,
    Sex,
    User,
)
from meditrack.schemas import DashboardOut, DashboardStats, MetaOut, RecentConsultation
from meditrack.security import current_user
from meditrack.storage import get_store

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(
    _: User = Depends(current_user), session: Session = Depends(get_session)
):
    today = date.today()
    day_start = datetime.combine(today, time.min)
    day_end = day_start + timedelta(days=1)

    todays = session.scalars(
        select(Appointment)
        .options(joinedload(Appointment.patient), joinedload(Appointment.doctor))
        .where(Appointment.scheduled_at >= day_start, Appointment.scheduled_at < day_end)
        .order_by(Appointment.scheduled_at)
    ).all()

    upcoming = session.scalars(
        select(Appointment)
        .options(joinedload(Appointment.patient), joinedload(Appointment.doctor))
        .where(
            Appointment.scheduled_at >= day_end,
            Appointment.status == AppointmentStatus.scheduled,
        )
        .order_by(Appointment.scheduled_at)
        .limit(8)
    ).all()

    recent_rows = session.scalars(
        select(Consultation)
        .options(joinedload(Consultation.patient))
        .order_by(Consultation.visited_at.desc())
        .limit(6)
    ).all()

    outstanding = session.scalar(
        select(func.coalesce(func.sum(Consultation.fee), 0)).where(
            Consultation.payment_status == PaymentStatus.unpaid
        )
    )

    return DashboardOut(
        today=today,
        stats=DashboardStats(
            patients=session.scalar(select(func.count(Patient.id))),
            doctors=session.scalar(select(func.count(Doctor.id))),
            today_total=len(todays),
            today_waiting=sum(1 for a in todays if a.status == AppointmentStatus.scheduled),
            consultations=session.scalar(select(func.count(Consultation.id))),
            outstanding=outstanding,
        ),
        todays=[_out(a) for a in todays],
        upcoming=[_out(a) for a in upcoming],
        recent=[
            RecentConsultation(
                id=c.id,
                visited_at=c.visited_at,
                patient_name=c.patient.full_name,
                diagnosis=c.diagnosis,
            )
            for c in recent_rows
        ],
    )


@router.get("/meta", response_model=MetaOut)
async def meta(_: User = Depends(current_user)):
    """Enumerations and limits, so the client does not hard-code them."""
    return MetaOut(
        app_name=config.APP_NAME,
        sexes=[s.value for s in Sex],
        appointment_statuses=[s.value for s in AppointmentStatus],
        payment_statuses=[s.value for s in PaymentStatus],
        slot_minutes=SLOT_MINUTES,
        max_attachment_bytes=config.MAX_ATTACHMENT_BYTES,
        allowed_attachment_types=config.ALLOWED_ATTACHMENT_TYPES,
        storage_backend=get_store().__class__.__name__,
    )
