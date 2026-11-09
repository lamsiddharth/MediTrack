"""API tests: the auth gate, each resource, and the rules that matter."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

PROTECTED = [
    ("get", "/api/auth/me"),
    ("get", "/api/dashboard"),
    ("get", "/api/meta"),
    ("get", "/api/patients"),
    ("get", "/api/doctors"),
    ("get", "/api/appointments"),
    ("get", "/api/consultations"),
    ("get", "/api/consultations/1"),
]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("method,path", PROTECTED)
def test_endpoints_require_login(client, method, path):
    client.cookies.clear()
    response = getattr(client, method)(path)
    assert response.status_code == 401
    assert response.json()["detail"] == "Not signed in"


def test_login_rejects_wrong_password(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401
    assert "Incorrect username or password" in r.json()["detail"]


def test_login_does_not_reveal_whether_user_exists(client):
    client.cookies.clear()
    unknown = client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    wrong = client.post("/api/auth/login", json={"username": "admin", "password": "x"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_login_me_logout_cycle(client):
    client.cookies.clear()
    login = client.post("/api/auth/login", json={"username": "admin", "password": "testpass123"})
    assert login.status_code == 200
    assert login.json()["username"] == "admin"

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["full_name"]

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_healthz_is_open(client):
    client.cookies.clear()
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Metadata and dashboard
# ---------------------------------------------------------------------------
def test_meta_exposes_enums_and_limits(auth):
    m = auth.get("/api/meta").json()
    assert m["sexes"] == ["Male", "Female", "Other"]
    assert "Scheduled" in m["appointment_statuses"]
    assert "Unpaid" in m["payment_statuses"]
    assert m["slot_minutes"] == 20
    assert m["max_attachment_bytes"] > 0
    assert ".pdf" in m["allowed_attachment_types"].values()


def test_dashboard_reports_seeded_clinic(auth):
    d = auth.get("/api/dashboard").json()
    assert d["stats"]["patients"] == 10
    assert d["stats"]["doctors"] == 5
    assert d["stats"]["consultations"] >= 4
    # One seeded consultation is left unpaid on purpose.
    assert float(d["stats"]["outstanding"]) > 0
    assert len(d["todays"]) >= 1
    assert d["todays"][0]["patient"]["full_name"]
    assert d["todays"][0]["doctor"]["specialisation"]


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------
def test_patient_list_pagination_shape(auth):
    body = auth.get("/api/patients").json()
    assert body["total"] == 10
    assert body["page"] == 1
    assert len(body["items"]) == 10
    assert body["has_next"] is False
    first = body["items"][0]
    assert first["mrn"].startswith("MRN-")
    assert isinstance(first["age"], int)


def test_patient_search(auth):
    hit = auth.get("/api/patients", params={"q": "Kavya"}).json()
    assert hit["total"] == 1
    assert hit["items"][0]["full_name"] == "Kavya Reddy"
    assert hit["items"][0]["allergies"] == "Penicillin"

    miss = auth.get("/api/patients", params={"q": "zzznotathing"}).json()
    assert miss["total"] == 0 and miss["items"] == []


def test_patient_search_matches_mrn_and_phone(auth):
    by_mrn = auth.get("/api/patients", params={"q": "MRN-00001"}).json()
    assert by_mrn["total"] == 1
    by_phone = auth.get("/api/patients", params={"q": "22003"}).json()
    assert by_phone["total"] == 1


def test_create_patient_allocates_sequential_mrn(auth):
    before = auth.get("/api/patients").json()["total"]
    r = auth.post(
        "/api/patients",
        json={
            "full_name": "Test Person",
            "date_of_birth": "1990-05-05",
            "sex": "Female",
            "phone": "+91 90000 00000",
            "blood_group": "O+",
        },
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["mrn"] == f"MRN-{before + 1:05d}"
    assert created["age"] == date.today().year - 1990 - (
        0 if (date.today().month, date.today().day) >= (5, 5) else 1
    )


def test_create_patient_rejects_future_dob(auth):
    r = auth.post(
        "/api/patients",
        json={
            "full_name": "Not Born",
            "date_of_birth": (date.today() + timedelta(days=1)).isoformat(),
            "sex": "Male",
            "phone": "+91 1",
        },
    )
    assert r.status_code == 422
    assert "future" in r.text


def test_create_patient_rejects_bad_date_and_unknown_sex(auth):
    bad_date = auth.post(
        "/api/patients",
        json={"full_name": "X", "date_of_birth": "not-a-date", "sex": "Male", "phone": "1"},
    )
    assert bad_date.status_code == 422

    bad_sex = auth.post(
        "/api/patients",
        json={"full_name": "X", "date_of_birth": "1990-01-01", "sex": "Martian", "phone": "1"},
    )
    assert bad_sex.status_code == 422


def test_update_patient(auth):
    pid = auth.get("/api/patients", params={"q": "Vikram"}).json()["items"][0]["id"]
    r = auth.put(
        f"/api/patients/{pid}",
        json={
            "full_name": "Vikram Singh",
            "date_of_birth": "1983-08-21",
            "sex": "Male",
            "phone": "+91 99100 22009",
            "allergies": "Ibuprofen",
        },
    )
    assert r.status_code == 200
    assert r.json()["allergies"] == "Ibuprofen"


def test_patient_sub_resources(auth):
    pid = auth.get("/api/patients", params={"q": "Kavya"}).json()["items"][0]["id"]
    appts = auth.get(f"/api/patients/{pid}/appointments")
    cons = auth.get(f"/api/patients/{pid}/consultations")
    assert appts.status_code == 200 and isinstance(appts.json(), list)
    assert cons.status_code == 200 and len(cons.json()) >= 1
    assert "dermatitis" in cons.json()[0]["diagnosis"].lower()


def test_unknown_patient_is_404(auth):
    assert auth.get("/api/patients/999999").status_code == 404


# ---------------------------------------------------------------------------
# Doctors
# ---------------------------------------------------------------------------
def test_doctor_list_and_create_and_update(auth):
    doctors = auth.get("/api/doctors").json()
    assert len(doctors) == 5
    assert any(d["specialisation"] == "Cardiology" for d in doctors)

    created = auth.post(
        "/api/doctors",
        json={"full_name": "Dr. New Hire", "specialisation": "ENT", "consultation_fee": "650"},
    )
    assert created.status_code == 201
    did = created.json()["id"]

    updated = auth.put(
        f"/api/doctors/{did}",
        json={
            "full_name": "Dr. New Hire",
            "specialisation": "ENT",
            "room": "215",
            "consultation_fee": "750",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["room"] == "215"
    assert float(updated.json()["consultation_fee"]) == 750.0


def test_doctor_rejects_negative_fee(auth):
    r = auth.post(
        "/api/doctors",
        json={"full_name": "Dr. Cheap", "specialisation": "GP", "consultation_fee": "-5"},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Appointments: the double-booking rule
# ---------------------------------------------------------------------------
def _book(auth, patient_id, doctor_id, when, reason="Test"):
    return auth.post(
        "/api/appointments",
        json={
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "scheduled_at": when.isoformat(),
            "reason": reason,
        },
    )


def test_appointments_for_a_day(auth):
    today = auth.get("/api/appointments").json()
    assert isinstance(today, list)
    assert all("patient" in a and "doctor" in a for a in today)

    filtered = auth.get("/api/appointments", params={"status": "Scheduled"}).json()
    assert all(a["status"] == "Scheduled" for a in filtered)


def test_booking_then_clash_is_refused(auth):
    slot = datetime.combine(date.today() + timedelta(days=30), datetime.min.time()).replace(hour=9)

    first = _book(auth, 1, 1, slot)
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "Scheduled"

    clash = _book(auth, 2, 1, slot)
    assert clash.status_code == 409
    assert "already has" in clash.json()["detail"]
    assert "20 minutes" in clash.json()["detail"]


def test_clash_window_covers_overlap(auth):
    base = datetime.combine(date.today() + timedelta(days=31), datetime.min.time()).replace(hour=14)
    assert _book(auth, 1, 2, base).status_code == 201
    assert _book(auth, 2, 2, base + timedelta(minutes=10)).status_code == 409


def test_different_doctor_same_time_allowed(auth):
    slot = datetime.combine(date.today() + timedelta(days=32), datetime.min.time()).replace(hour=11)
    assert _book(auth, 1, 3, slot).status_code == 201
    assert _book(auth, 2, 4, slot).status_code == 201


def test_booking_outside_slot_window_allowed(auth):
    base = datetime.combine(date.today() + timedelta(days=33), datetime.min.time()).replace(hour=16)
    assert _book(auth, 1, 5, base).status_code == 201
    assert _book(auth, 2, 5, base + timedelta(minutes=20)).status_code == 201


def test_cancelling_releases_the_slot(auth):
    slot = datetime.combine(date.today() + timedelta(days=34), datetime.min.time()).replace(hour=10)
    first = _book(auth, 1, 1, slot)
    aid = first.json()["id"]

    assert _book(auth, 2, 1, slot).status_code == 409

    cancelled = auth.patch(f"/api/appointments/{aid}/status", json={"status": "Cancelled"})
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "Cancelled"

    # The slot is now free.
    assert _book(auth, 2, 1, slot).status_code == 201


def test_booking_unknown_patient_or_doctor(auth):
    slot = datetime.combine(date.today() + timedelta(days=35), datetime.min.time()).replace(hour=9)
    assert _book(auth, 999999, 1, slot).status_code == 404
    assert _book(auth, 1, 999999, slot).status_code == 404


def test_status_validation(auth):
    slot = datetime.combine(date.today() + timedelta(days=36), datetime.min.time()).replace(hour=9)
    aid = _book(auth, 1, 1, slot).json()["id"]
    assert auth.patch(f"/api/appointments/{aid}/status", json={"status": "Elsewhere"}).status_code == 422
    assert auth.patch("/api/appointments/999999/status", json={"status": "Cancelled"}).status_code == 404


# ---------------------------------------------------------------------------
# Consultations
# ---------------------------------------------------------------------------
def test_consultation_list_and_unpaid_filter(auth):
    all_rows = auth.get("/api/consultations").json()
    unpaid = auth.get("/api/consultations", params={"unpaid": "true"}).json()
    assert len(all_rows) >= len(unpaid) >= 1
    assert all(c["payment_status"] == "Unpaid" for c in unpaid)


def test_consultation_detail_includes_allergies_and_notes(auth):
    detail = auth.get("/api/consultations/1").json()
    assert detail["diagnosis"]
    assert "patient" in detail and "doctor" in detail
    assert "session_notes" in detail and isinstance(detail["session_notes"], list)
    assert "patient_allergies" in detail


def test_recording_a_visit_completes_the_appointment(auth):
    slot = datetime.combine(date.today() + timedelta(days=40), datetime.min.time()).replace(hour=8)
    aid = _book(auth, 3, 1, slot).json()["id"]

    created = auth.post(
        "/api/consultations",
        json={
            "patient_id": 3,
            "doctor_id": 1,
            "appointment_id": aid,
            "diagnosis": "Seasonal allergic rhinitis",
            "symptoms": "Sneezing, watery eyes",
            "prescription": "Cetirizine 10mg nightly",
            "follow_up_on": (date.today() + timedelta(days=30)).isoformat(),
            "fee": "500",
            "payment_status": "Paid",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["payment_status"] == "Paid"

    day = auth.get("/api/appointments", params={"on": slot.date().isoformat()}).json()
    booked = next(a for a in day if a["id"] == aid)
    assert booked["status"] == "Completed"
    assert booked["consultation_id"] == created.json()["id"]


def test_consultation_requires_diagnosis_and_rejects_negative_fee(auth):
    assert auth.post(
        "/api/consultations", json={"patient_id": 1, "doctor_id": 1, "diagnosis": "   "}
    ).status_code == 422
    assert auth.post(
        "/api/consultations",
        json={"patient_id": 1, "doctor_id": 1, "diagnosis": "x", "fee": "-5"},
    ).status_code == 422


def test_one_consultation_per_appointment(auth):
    slot = datetime.combine(date.today() + timedelta(days=41), datetime.min.time()).replace(hour=9)
    aid = _book(auth, 4, 2, slot).json()["id"]
    payload = {"patient_id": 4, "doctor_id": 2, "appointment_id": aid, "diagnosis": "First"}
    assert auth.post("/api/consultations", json=payload).status_code == 201
    second = auth.post("/api/consultations", json={**payload, "diagnosis": "Second"})
    assert second.status_code == 409
    assert "already has a consultation" in second.json()["detail"]


def test_walk_in_needs_no_appointment(auth):
    r = auth.post(
        "/api/consultations",
        json={"patient_id": 5, "doctor_id": 3, "diagnosis": "Walk-in: sprained wrist"},
    )
    assert r.status_code == 201


def test_payment_status_update(auth):
    cid = auth.get("/api/consultations", params={"unpaid": "true"}).json()[0]["id"]
    r = auth.patch(f"/api/consultations/{cid}/payment", json={"payment_status": "Paid"})
    assert r.status_code == 200 and r.json()["payment_status"] == "Paid"

    assert auth.patch(
        f"/api/consultations/{cid}/payment", json={"payment_status": "Bartered"}
    ).status_code == 422


def test_unknown_consultation_is_404(auth):
    assert auth.get("/api/consultations/999999").status_code == 404


# ---------------------------------------------------------------------------
# Password change
# ---------------------------------------------------------------------------
def test_password_change_validation_then_success(auth):
    bad = auth.post(
        "/api/auth/password",
        json={"current_password": "nope", "new_password": "brandnewpass1"},
    )
    assert bad.status_code == 400 and "not correct" in bad.json()["detail"]

    short = auth.post(
        "/api/auth/password",
        json={"current_password": "testpass123", "new_password": "short"},
    )
    assert short.status_code == 400 and "at least 8" in short.json()["detail"]

    same = auth.post(
        "/api/auth/password",
        json={"current_password": "testpass123", "new_password": "testpass123"},
    )
    assert same.status_code == 400

    ok = auth.post(
        "/api/auth/password",
        json={"current_password": "testpass123", "new_password": "brandnewpass1"},
    )
    assert ok.status_code == 200

    auth.cookies.clear()
    assert auth.post(
        "/api/auth/login", json={"username": "admin", "password": "testpass123"}
    ).status_code == 401
    assert auth.post(
        "/api/auth/login", json={"username": "admin", "password": "brandnewpass1"}
    ).status_code == 200

    # Restore, so the shared account stays usable for tests that run later.
    restored = auth.post(
        "/api/auth/password",
        json={"current_password": "brandnewpass1", "new_password": "testpass123"},
    )
    assert restored.status_code == 200
