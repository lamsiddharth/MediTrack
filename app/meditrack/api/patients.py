"""Patient endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from meditrack.db import get_session
from meditrack.models import Patient, Sex, User, next_mrn
from meditrack.schemas import (
    AppointmentOut,
    ConsultationOut,
    PatientIn,
    PatientListOut,
    PatientOut,
)
from meditrack.api.appointments import _out as appointment_out
from meditrack.security import current_user

router = APIRouter(prefix="/api/patients", tags=["patients"])

PAGE_SIZE = 15


@router.get("", response_model=PatientListOut)
async def list_patients(
    q: str = "",
    page: int = 1,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    page = max(1, page)
    stmt = select(Patient)
    count_stmt = select(func.count(Patient.id))

    term = q.strip()
    if term:
        like = f"%{term}%"
        condition = or_(
            Patient.full_name.ilike(like),
            Patient.mrn.ilike(like),
            Patient.phone.ilike(like),
        )
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = session.scalar(count_stmt)
    items = session.scalars(
        stmt.order_by(Patient.full_name).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    ).all()

    return PatientListOut(
        items=[PatientOut.model_validate(p) for p in items],
        total=total,
        page=page,
        page_size=PAGE_SIZE,
        has_next=page * PAGE_SIZE < total,
    )


def _apply(patient: Patient, payload: PatientIn) -> None:
    patient.full_name = payload.full_name.strip()
    patient.date_of_birth = payload.date_of_birth
    patient.sex = Sex(payload.sex)
    patient.phone = payload.phone.strip()
    patient.address = (payload.address or "").strip() or None
    patient.blood_group = (payload.blood_group or "").strip() or None
    patient.allergies = (payload.allergies or "").strip() or None


@router.post("", response_model=PatientOut, status_code=201)
async def create_patient(
    payload: PatientIn,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    try:
        Sex(payload.sex)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Unknown sex: {payload.sex}")

    patient = Patient(mrn=next_mrn(session))
    _apply(patient, payload)
    session.add(patient)
    session.commit()
    return patient


def _get(session: Session, patient_id: int) -> Patient:
    patient = session.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@router.get("/{patient_id}", response_model=PatientOut)
async def get_patient(
    patient_id: int,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    return _get(session, patient_id)


@router.get("/{patient_id}/appointments", response_model=list[AppointmentOut])
async def patient_appointments(
    patient_id: int,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    patient = _get(session, patient_id)
    return [appointment_out(a) for a in patient.appointments]


@router.get("/{patient_id}/consultations", response_model=list[ConsultationOut])
async def patient_consultations(
    patient_id: int,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    return _get(session, patient_id).consultations


@router.put("/{patient_id}", response_model=PatientOut)
async def update_patient(
    patient_id: int,
    payload: PatientIn,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    patient = _get(session, patient_id)
    try:
        Sex(payload.sex)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Unknown sex: {payload.sex}")
    _apply(patient, payload)
    session.commit()
    return patient
