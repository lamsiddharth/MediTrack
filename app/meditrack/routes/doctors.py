"""The doctor roster."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from meditrack.db import get_session
from meditrack.models import Doctor, User
from meditrack.security import current_user
from meditrack.templating import templates

router = APIRouter(prefix="/doctors")


@router.get("")
async def list_doctors(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    doctors = session.scalars(select(Doctor).order_by(Doctor.full_name)).all()
    return templates.TemplateResponse(
        request, "doctors/list.html", {"user": user, "doctors": doctors}
    )


@router.get("/new")
async def new_doctor(request: Request, user: User = Depends(current_user)):
    return templates.TemplateResponse(
        request, "doctors/form.html", {"user": user, "doctor": None, "error": None}
    )


def _parse_fee(raw: str) -> float:
    try:
        fee = float(raw or 0)
    except ValueError:
        raise ValueError("The consultation fee must be a number.")
    if fee < 0:
        raise ValueError("The consultation fee cannot be negative.")
    return fee


@router.post("/new")
async def create_doctor(
    request: Request,
    full_name: str = Form(...),
    specialisation: str = Form(...),
    phone: str = Form(""),
    room: str = Form(""),
    consultation_fee: str = Form("0"),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    try:
        fee = _parse_fee(consultation_fee)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "doctors/form.html",
            {"user": user, "doctor": None, "error": str(exc)},
            status_code=400,
        )

    doctor = Doctor(
        full_name=full_name.strip(),
        specialisation=specialisation.strip(),
        phone=phone.strip() or None,
        room=room.strip() or None,
        consultation_fee=fee,
    )
    session.add(doctor)
    session.commit()
    return RedirectResponse("/doctors", status_code=303)


@router.get("/{doctor_id}/edit")
async def edit_doctor(
    request: Request,
    doctor_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    doctor = session.get(Doctor, doctor_id)
    if doctor is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request, "doctors/form.html", {"user": user, "doctor": doctor, "error": None}
    )


@router.post("/{doctor_id}/edit")
async def update_doctor(
    request: Request,
    doctor_id: int,
    full_name: str = Form(...),
    specialisation: str = Form(...),
    phone: str = Form(""),
    room: str = Form(""),
    consultation_fee: str = Form("0"),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    doctor = session.get(Doctor, doctor_id)
    if doctor is None:
        raise HTTPException(status_code=404)

    try:
        fee = _parse_fee(consultation_fee)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "doctors/form.html",
            {"user": user, "doctor": doctor, "error": str(exc)},
            status_code=400,
        )

    doctor.full_name = full_name.strip()
    doctor.specialisation = specialisation.strip()
    doctor.phone = phone.strip() or None
    doctor.room = room.strip() or None
    doctor.consultation_fee = fee
    session.commit()
    return RedirectResponse("/doctors", status_code=303)
