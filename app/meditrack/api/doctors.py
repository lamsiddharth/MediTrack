"""Doctor roster endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from meditrack.db import get_session
from meditrack.models import Doctor, User
from meditrack.schemas import DoctorIn, DoctorOut
from meditrack.security import current_user

router = APIRouter(prefix="/api/doctors", tags=["doctors"])


@router.get("", response_model=list[DoctorOut])
async def list_doctors(
    _: User = Depends(current_user), session: Session = Depends(get_session)
):
    return session.scalars(select(Doctor).order_by(Doctor.full_name)).all()


def _apply(doctor: Doctor, payload: DoctorIn) -> None:
    doctor.full_name = payload.full_name.strip()
    doctor.specialisation = payload.specialisation.strip()
    doctor.phone = (payload.phone or "").strip() or None
    doctor.room = (payload.room or "").strip() or None
    doctor.consultation_fee = payload.consultation_fee


@router.post("", response_model=DoctorOut, status_code=201)
async def create_doctor(
    payload: DoctorIn,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    doctor = Doctor()
    _apply(doctor, payload)
    session.add(doctor)
    session.commit()
    return doctor


@router.put("/{doctor_id}", response_model=DoctorOut)
async def update_doctor(
    doctor_id: int,
    payload: DoctorIn,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    doctor = session.get(Doctor, doctor_id)
    if doctor is None:
        raise HTTPException(status_code=404, detail="Doctor not found")
    _apply(doctor, payload)
    session.commit()
    return doctor
