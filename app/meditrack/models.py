"""Data model.

Five tables, which is enough to cover the real workflow of a small clinic:
a patient is registered, booked in with a doctor, and the visit produces a
consultation record. Billing hangs off the consultation.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Sex(str, enum.Enum):
    male = "Male"
    female = "Female"
    other = "Other"


class AppointmentStatus(str, enum.Enum):
    scheduled = "Scheduled"
    completed = "Completed"
    cancelled = "Cancelled"
    no_show = "No show"


class PaymentStatus(str, enum.Enum):
    unpaid = "Unpaid"
    paid = "Paid"
    waived = "Waived"


class User(Base):
    """A staff login. Deliberately minimal: one account type, no roles."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Medical record number: the human-facing identifier staff actually quote.
    mrn: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120), index=True)
    date_of_birth: Mapped[date] = mapped_column(Date)
    sex: Mapped[Sex] = mapped_column(Enum(Sex, native_enum=False, length=10))
    phone: Mapped[str] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    blood_group: Mapped[str | None] = mapped_column(String(8), nullable=True)
    allergies: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    appointments: Mapped[list[Appointment]] = relationship(
        back_populates="patient", cascade="all, delete-orphan", order_by="Appointment.scheduled_at.desc()"
    )
    consultations: Mapped[list[Consultation]] = relationship(
        back_populates="patient", cascade="all, delete-orphan", order_by="Consultation.visited_at.desc()"
    )

    @property
    def age(self) -> int:
        """Age in whole years, today."""
        today = date.today()
        had_birthday = (today.month, today.day) >= (self.date_of_birth.month, self.date_of_birth.day)
        return today.year - self.date_of_birth.year - (0 if had_birthday else 1)


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), index=True)
    specialisation: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    room: Mapped[str | None] = mapped_column(String(16), nullable=True)
    consultation_fee: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    appointments: Mapped[list[Appointment]] = relationship(back_populates="doctor")
    consultations: Mapped[list[Consultation]] = relationship(back_populates="doctor")


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus, native_enum=False, length=12), default=AppointmentStatus.scheduled, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    patient: Mapped[Patient] = relationship(back_populates="appointments")
    doctor: Mapped[Doctor] = relationship(back_populates="appointments")
    consultation: Mapped[Consultation | None] = relationship(
        back_populates="appointment", uselist=False
    )


class Consultation(Base):
    """What happened during a visit. This is the clinical record."""

    __tablename__ = "consultations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), index=True)
    # Nullable so a walk-in can be recorded without a prior booking.
    appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    visited_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    symptoms: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnosis: Mapped[str] = mapped_column(Text)
    prescription: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    fee: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    payment_status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False, length=10), default=PaymentStatus.unpaid, index=True
    )

    patient: Mapped[Patient] = relationship(back_populates="consultations")
    doctor: Mapped[Doctor] = relationship(back_populates="consultations")
    appointment: Mapped[Appointment | None] = relationship(back_populates="consultation")
    session_notes: Mapped[list[SessionNote]] = relationship(
        back_populates="consultation",
        cascade="all, delete-orphan",
        order_by="SessionNote.created_at",
    )


class SessionNote(Base):
    """A progress note added to a session after the initial write-up.

    The note text and any attached document live in object storage, not here;
    this table holds only the metadata and the keys needed to fetch them. That
    keeps clinical narrative and binaries out of a SQLite file that sits on one
    instance's disk.

    Notes are append-only: there is no edit or delete route. A clinical record
    that can be silently rewritten is not much of a record.
    """

    __tablename__ = "session_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    consultation_id: Mapped[int] = mapped_column(
        ForeignKey("consultations.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    # Short label so the timeline is scannable without fetching every body.
    title: Mapped[str] = mapped_column(String(120))

    # Random per-note prefix, so object keys never depend on a database id.
    storage_uid: Mapped[str] = mapped_column(String(32), unique=True, index=True)

    body_key: Mapped[str] = mapped_column(String(255))
    body_bytes: Mapped[int] = mapped_column(Integer, default=0)

    attachment_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attachment_filename: Mapped[str | None] = mapped_column(String(160), nullable=True)
    attachment_content_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    attachment_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    consultation: Mapped[Consultation] = relationship(back_populates="session_notes")
    author: Mapped[User] = relationship()

    @property
    def has_attachment(self) -> bool:
        return bool(self.attachment_key)

    @property
    def attachment_size_label(self) -> str:
        size = self.attachment_bytes or 0
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.0f} KB"
        return f"{size / (1024 * 1024):.1f} MB"


def next_mrn(session) -> str:
    """Allocate the next medical record number, as MRN-00001.

    Derived from the highest existing number rather than a row count, so
    deleting a patient cannot cause a collision.
    """
    highest = session.query(func.max(Patient.mrn)).scalar()
    nxt = 1 if not highest else int(highest.split("-")[-1]) + 1
    return f"MRN-{nxt:05d}"
