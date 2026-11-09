"""Patient registration, search and records."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from meditrack.db import get_session
from meditrack.models import Patient, Sex, User, next_mrn
from meditrack.security import current_user
from meditrack.templating import templates

router = APIRouter(prefix="/patients")

PAGE_SIZE = 15


@router.get("")
async def list_patients(
    request: Request,
    q: str = "",
    page: int = 1,
    user: User = Depends(current_user),
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
    patients = session.scalars(
        stmt.order_by(Patient.full_name).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    ).all()

    return templates.TemplateResponse(
        request,
        "patients/list.html",
        {
            "user": user,
            "patients": patients,
            "q": term,
            "page": page,
            "total": total,
            "page_size": PAGE_SIZE,
            "has_next": page * PAGE_SIZE < total,
        },
    )


@router.get("/new")
async def new_patient(request: Request, user: User = Depends(current_user)):
    return templates.TemplateResponse(
        request,
        "patients/form.html",
        {"user": user, "patient": None, "sexes": list(Sex), "error": None},
    )


def _parse_dob(raw: str) -> date:
    try:
        dob = date.fromisoformat(raw)
    except ValueError:
        raise ValueError("Enter the date of birth as YYYY-MM-DD.")
    if dob > date.today():
        raise ValueError("The date of birth cannot be in the future.")
    if dob.year < 1900:
        raise ValueError("That date of birth looks wrong.")
    return dob


@router.post("/new")
async def create_patient(
    request: Request,
    full_name: str = Form(...),
    date_of_birth: str = Form(...),
    sex: str = Form(...),
    phone: str = Form(...),
    address: str = Form(""),
    blood_group: str = Form(""),
    allergies: str = Form(""),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    try:
        dob = _parse_dob(date_of_birth)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "patients/form.html",
            {"user": user, "patient": None, "sexes": list(Sex), "error": str(exc)},
            status_code=400,
        )

    patient = Patient(
        mrn=next_mrn(session),
        full_name=full_name.strip(),
        date_of_birth=dob,
        sex=Sex(sex),
        phone=phone.strip(),
        address=address.strip() or None,
        blood_group=blood_group.strip() or None,
        allergies=allergies.strip() or None,
    )
    session.add(patient)
    session.commit()

    return RedirectResponse(f"/patients/{patient.id}", status_code=303)


def _get_patient(session: Session, patient_id: int) -> Patient:
    patient = session.get(
        Patient,
        patient_id,
        options=[
            joinedload(Patient.appointments),
            joinedload(Patient.consultations),
        ],
    )
    if patient is None:
        raise HTTPException(status_code=404)
    return patient


@router.get("/{patient_id}")
async def patient_detail(
    request: Request,
    patient_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    patient = _get_patient(session, patient_id)
    return templates.TemplateResponse(
        request, "patients/detail.html", {"user": user, "patient": patient}
    )


@router.get("/{patient_id}/edit")
async def edit_patient(
    request: Request,
    patient_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    patient = _get_patient(session, patient_id)
    return templates.TemplateResponse(
        request,
        "patients/form.html",
        {"user": user, "patient": patient, "sexes": list(Sex), "error": None},
    )


@router.post("/{patient_id}/edit")
async def update_patient(
    request: Request,
    patient_id: int,
    full_name: str = Form(...),
    date_of_birth: str = Form(...),
    sex: str = Form(...),
    phone: str = Form(...),
    address: str = Form(""),
    blood_group: str = Form(""),
    allergies: str = Form(""),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    patient = _get_patient(session, patient_id)

    try:
        dob = _parse_dob(date_of_birth)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "patients/form.html",
            {"user": user, "patient": patient, "sexes": list(Sex), "error": str(exc)},
            status_code=400,
        )

    patient.full_name = full_name.strip()
    patient.date_of_birth = dob
    patient.sex = Sex(sex)
    patient.phone = phone.strip()
    patient.address = address.strip() or None
    patient.blood_group = blood_group.strip() or None
    patient.allergies = allergies.strip() or None
    session.commit()

    return RedirectResponse(f"/patients/{patient.id}", status_code=303)
