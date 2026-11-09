"""Create the schema, the login account, and demo records on an empty database.

Everything here is synthetic. Do not put real patient data in this deployment
without first putting it behind TLS and restricted access.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from meditrack import config
from meditrack.db import SessionLocal, engine
from meditrack.models import (
    Appointment,
    AppointmentStatus,
    Base,
    Consultation,
    Doctor,
    Patient,
    PaymentStatus,
    Sex,
    User,
)
from meditrack.security import hash_password

log = logging.getLogger("meditrack.seed")

DOCTORS = [
    ("Dr. Priya Nair", "General Medicine", "+91 98200 11234", "101", 500),
    ("Dr. Rahul Verma", "Cardiology", "+91 98200 11235", "204", 1200),
    ("Dr. Aisha Khan", "Paediatrics", "+91 98200 11236", "108", 700),
    ("Dr. Sanjay Rao", "Orthopaedics", "+91 98200 11237", "309", 900),
    ("Dr. Meera Iyer", "Dermatology", "+91 98200 11238", "112", 800),
]

PATIENTS = [
    # name, dob, sex, phone, blood group, allergies, address
    ("Arjun Sharma", date(1986, 3, 14), Sex.male, "+91 99100 22001", "O+", None, "12 Hill Road, Bandra"),
    ("Kavya Reddy", date(1994, 7, 2), Sex.female, "+91 99100 22002", "A+", "Penicillin", "44 Lake View, Powai"),
    ("Imran Sheikh", date(1971, 11, 23), Sex.male, "+91 99100 22003", "B+", None, "7 Station Lane, Dadar"),
    ("Neha Joshi", date(2001, 1, 30), Sex.female, "+91 99100 22004", "AB-", "Sulfa drugs", "88 Palm Grove, Andheri"),
    ("Rohan Mehta", date(1959, 6, 9), Sex.male, "+91 99100 22005", "O-", "Aspirin", "3 Church Street, Colaba"),
    ("Divya Pillai", date(1990, 9, 17), Sex.female, "+91 99100 22006", "A-", None, "21 Garden Road, Mahim"),
    ("Sameer Gupta", date(2018, 4, 5), Sex.male, "+91 99100 22007", "B-", "Peanuts", "56 Sunrise Apts, Vile Parle"),
    ("Lakshmi Menon", date(1948, 12, 1), Sex.female, "+91 99100 22008", "O+", None, "9 Temple Street, Matunga"),
    ("Vikram Singh", date(1983, 8, 21), Sex.male, "+91 99100 22009", "AB+", None, "77 Marine Lines"),
    ("Fatima Ansari", date(1996, 2, 11), Sex.female, "+91 99100 22010", "A+", "Latex", "14 Rose Villa, Khar"),
]

# (patient index, doctor index, day offset from today, hour, minute, status, reason)
APPOINTMENTS = [
    (0, 0, 0, 9, 30, AppointmentStatus.completed, "Persistent cough"),
    (1, 4, 0, 10, 0, AppointmentStatus.completed, "Skin rash on forearm"),
    (2, 1, 0, 11, 15, AppointmentStatus.scheduled, "Chest tightness on exertion"),
    (6, 2, 0, 12, 0, AppointmentStatus.scheduled, "Fever and sore throat"),
    (4, 1, 0, 15, 30, AppointmentStatus.scheduled, "Blood pressure review"),
    (7, 3, 1, 9, 0, AppointmentStatus.scheduled, "Knee pain, difficulty on stairs"),
    (3, 0, 1, 10, 45, AppointmentStatus.scheduled, "Recurring migraine"),
    (8, 0, 2, 14, 0, AppointmentStatus.scheduled, "Annual health check"),
    (5, 4, 3, 11, 30, AppointmentStatus.scheduled, "Hair loss consultation"),
    (9, 2, -2, 10, 0, AppointmentStatus.completed, "Vaccination follow-up"),
    (0, 1, -5, 16, 0, AppointmentStatus.completed, "ECG review"),
    (2, 0, -9, 9, 15, AppointmentStatus.no_show, "General consultation"),
    (4, 3, -14, 13, 0, AppointmentStatus.cancelled, "Shoulder stiffness"),
]

# Clinical records, keyed to the completed appointments above by their index.
CONSULTATIONS = [
    # appt index, symptoms, diagnosis, prescription, notes, follow-up days, paid
    (
        0,
        "Dry cough for three weeks, worse at night. No fever.",
        "Post-viral cough with mild bronchial irritation.",
        "Levosalbutamol syrup 5ml twice daily for 5 days.\nSteam inhalation twice daily.",
        "Advised to return if breathlessness develops.",
        14,
        PaymentStatus.paid,
    ),
    (
        1,
        "Itchy red patches on both forearms for ten days.",
        "Contact dermatitis, likely detergent-related.",
        "Mometasone cream, thin layer at night for 10 days.\nCetirizine 10mg at bedtime if itching.",
        "Advised switching to a fragrance-free detergent and using gloves.",
        21,
        PaymentStatus.paid,
    ),
    (
        9,
        "Routine review after second dose. No adverse reaction reported.",
        "Immunisation schedule on track.",
        "No medication required.",
        "Next dose due in six months. Growth chart within normal range.",
        180,
        PaymentStatus.paid,
    ),
    (
        10,
        "Follow-up for intermittent palpitations. ECG taken on arrival.",
        "Benign ectopic beats. No structural abnormality on ECG.",
        "Reduce caffeine intake.\nContinue current medication unchanged.",
        "Reassured. Advised to log episodes and report if frequency rises.",
        90,
        PaymentStatus.unpaid,
    ),
]


def _seed_demo(session: Session) -> None:
    doctors = [
        Doctor(full_name=n, specialisation=s, phone=p, room=r, consultation_fee=f)
        for n, s, p, r, f in DOCTORS
    ]
    session.add_all(doctors)
    session.flush()

    patients = []
    for i, (name, dob, sex, phone, blood, allergies, address) in enumerate(PATIENTS, start=1):
        patients.append(
            Patient(
                mrn=f"MRN-{i:05d}",
                full_name=name,
                date_of_birth=dob,
                sex=sex,
                phone=phone,
                blood_group=blood,
                allergies=allergies,
                address=address,
            )
        )
    session.add_all(patients)
    session.flush()

    today = date.today()
    appointments = []
    for p_idx, d_idx, day_offset, hour, minute, status, reason in APPOINTMENTS:
        when = datetime.combine(today + timedelta(days=day_offset), time(hour, minute))
        appointments.append(
            Appointment(
                patient_id=patients[p_idx].id,
                doctor_id=doctors[d_idx].id,
                scheduled_at=when,
                reason=reason,
                status=status,
            )
        )
    session.add_all(appointments)
    session.flush()

    for a_idx, symptoms, diagnosis, prescription, notes, follow_days, paid in CONSULTATIONS:
        appt = appointments[a_idx]
        doctor = next(d for d in doctors if d.id == appt.doctor_id)
        session.add(
            Consultation(
                patient_id=appt.patient_id,
                doctor_id=appt.doctor_id,
                appointment_id=appt.id,
                visited_at=appt.scheduled_at,
                symptoms=symptoms,
                diagnosis=diagnosis,
                prescription=prescription,
                notes=notes,
                follow_up_on=appt.scheduled_at.date() + timedelta(days=follow_days),
                fee=doctor.consultation_fee,
                payment_status=paid,
            )
        )

    log.info(
        "seeded %d doctors, %d patients, %d appointments, %d consultations",
        len(doctors),
        len(patients),
        len(appointments),
        len(CONSULTATIONS),
    )


def init_db() -> None:
    """Create tables, ensure the login account exists, and seed demo data once."""
    Base.metadata.create_all(engine)

    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == config.SEED_USERNAME))
        if user is None:
            session.add(
                User(
                    username=config.SEED_USERNAME,
                    password_hash=hash_password(config.SEED_PASSWORD),
                    full_name=config.SEED_FULL_NAME,
                )
            )
            log.info("created login account %r", config.SEED_USERNAME)

        # Demo data only on a genuinely empty database, so a restart never
        # duplicates records or resurrects ones that were deleted on purpose.
        if config.SEED_DEMO_DATA and session.scalar(select(Patient).limit(1)) is None:
            _seed_demo(session)

        session.commit()
