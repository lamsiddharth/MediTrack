"""Pydantic schemas for the JSON API.

These are the API's contract with the React client. They are deliberately
separate from the SQLAlchemy models so that a column rename does not silently
change the shape of a response.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _non_blank(field_label: str):
    """Reject text that is empty once trimmed.

    `min_length` alone is not enough: a string of spaces satisfies it, which
    would allow a consultation to be saved with a blank diagnosis.
    """

    def check(v: str) -> str:
        if v is None or not v.strip():
            raise ValueError(f"{field_label} is required.")
        return v.strip()

    return check


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class LoginIn(BaseModel):
    username: str
    password: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


class UserOut(ORMModel):
    id: int
    username: str
    full_name: str
    last_login_at: datetime | None = None


# ---------------------------------------------------------------------------
# Doctors
# ---------------------------------------------------------------------------
class DoctorIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    specialisation: str = Field(min_length=1, max_length=80)
    phone: str | None = Field(default=None, max_length=32)
    room: str | None = Field(default=None, max_length=16)
    consultation_fee: Decimal = Field(default=Decimal(0), ge=0)

    _strip_name = field_validator("full_name")(_non_blank("A doctor name"))
    _strip_spec = field_validator("specialisation")(_non_blank("A specialisation"))


class DoctorOut(ORMModel):
    id: int
    full_name: str
    specialisation: str
    phone: str | None
    room: str | None
    consultation_fee: Decimal


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------
class PatientIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    date_of_birth: date
    sex: str
    phone: str = Field(min_length=1, max_length=32)
    address: str | None = Field(default=None, max_length=255)
    blood_group: str | None = Field(default=None, max_length=8)
    allergies: str | None = None

    _strip_name = field_validator("full_name")(_non_blank("A patient name"))
    _strip_phone = field_validator("phone")(_non_blank("A phone number"))

    @field_validator("date_of_birth")
    @classmethod
    def _sane_dob(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("The date of birth cannot be in the future.")
        if v.year < 1900:
            raise ValueError("That date of birth looks wrong.")
        return v


class PatientOut(ORMModel):
    id: int
    mrn: str
    full_name: str
    date_of_birth: date
    age: int
    sex: str
    phone: str
    address: str | None
    blood_group: str | None
    allergies: str | None
    created_at: datetime

    @field_validator("sex", mode="before")
    @classmethod
    def _enum_value(cls, v):
        return getattr(v, "value", v)


class PatientListOut(BaseModel):
    items: list[PatientOut]
    total: int
    page: int
    page_size: int
    has_next: bool


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------
class AppointmentIn(BaseModel):
    patient_id: int
    doctor_id: int
    scheduled_at: datetime
    reason: str | None = Field(default=None, max_length=255)


class AppointmentStatusIn(BaseModel):
    status: str


class PersonRef(ORMModel):
    id: int
    full_name: str


class DoctorRef(PersonRef):
    specialisation: str


class PatientRef(PersonRef):
    mrn: str


class AppointmentOut(ORMModel):
    id: int
    scheduled_at: datetime
    reason: str | None
    status: str
    patient: PatientRef
    doctor: DoctorRef
    consultation_id: int | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _enum_value(cls, v):
        return getattr(v, "value", v)


# ---------------------------------------------------------------------------
# Session notes
# ---------------------------------------------------------------------------
class SessionNoteOut(ORMModel):
    id: int
    title: str
    created_at: datetime
    author_name: str
    body: str | None = None
    unavailable: bool = False
    attachment_filename: str | None = None
    attachment_size_label: str | None = None
    has_attachment: bool = False


# ---------------------------------------------------------------------------
# Consultations
# ---------------------------------------------------------------------------
class ConsultationIn(BaseModel):
    patient_id: int
    doctor_id: int
    appointment_id: int | None = None
    diagnosis: str
    symptoms: str | None = None
    prescription: str | None = None
    notes: str | None = None
    follow_up_on: date | None = None
    fee: Decimal = Field(default=Decimal(0), ge=0)
    payment_status: str = "Unpaid"


    _strip_diagnosis = field_validator("diagnosis")(_non_blank("A diagnosis"))


class PaymentStatusIn(BaseModel):
    payment_status: str


class ConsultationOut(ORMModel):
    id: int
    visited_at: datetime
    symptoms: str | None
    diagnosis: str
    prescription: str | None
    notes: str | None
    follow_up_on: date | None
    fee: Decimal
    payment_status: str
    patient: PatientRef
    doctor: DoctorRef

    @field_validator("payment_status", mode="before")
    @classmethod
    def _enum_value(cls, v):
        return getattr(v, "value", v)


class ConsultationDetailOut(ConsultationOut):
    patient_allergies: str | None = None
    session_notes: list[SessionNoteOut] = []


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
class DashboardStats(BaseModel):
    patients: int
    doctors: int
    today_total: int
    today_waiting: int
    consultations: int
    outstanding: Decimal


class RecentConsultation(BaseModel):
    id: int
    visited_at: datetime
    patient_name: str
    diagnosis: str


class DashboardOut(BaseModel):
    today: date
    stats: DashboardStats
    todays: list[AppointmentOut]
    upcoming: list[AppointmentOut]
    recent: list[RecentConsultation]


# ---------------------------------------------------------------------------
# Metadata, so the client does not hard-code enum values
# ---------------------------------------------------------------------------
class MetaOut(BaseModel):
    app_name: str
    sexes: list[str]
    appointment_statuses: list[str]
    payment_statuses: list[str]
    slot_minutes: int
    max_attachment_bytes: int
    allowed_attachment_types: dict[str, str]
    storage_backend: str
