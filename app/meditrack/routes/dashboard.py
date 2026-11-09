"""The landing page: what the clinic looks like right now."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from meditrack.db import get_session
from meditrack.models import (
    Appointment,
    AppointmentStatus,
    Consultation,
    Doctor,
    Patient,
    PaymentStatus,
    User,
)
from meditrack.security import current_user
from meditrack.templating import templates

router = APIRouter()


@router.get("/")
async def dashboard(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
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

    recent = session.scalars(
        select(Consultation)
        .options(joinedload(Consultation.patient), joinedload(Consultation.doctor))
        .order_by(Consultation.visited_at.desc())
        .limit(6)
    ).all()

    outstanding = session.scalar(
        select(func.coalesce(func.sum(Consultation.fee), 0)).where(
            Consultation.payment_status == PaymentStatus.unpaid
        )
    )

    stats = {
        "patients": session.scalar(select(func.count(Patient.id))),
        "doctors": session.scalar(select(func.count(Doctor.id))),
        "today_total": len(todays),
        "today_waiting": sum(1 for a in todays if a.status == AppointmentStatus.scheduled),
        "consultations": session.scalar(select(func.count(Consultation.id))),
        "outstanding": outstanding,
    }

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "today": today,
            "stats": stats,
            "todays": todays,
            "upcoming": upcoming,
            "recent": recent,
        },
    )
