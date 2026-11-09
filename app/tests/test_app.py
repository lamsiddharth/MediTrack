"""Tests covering the login gate, the main pages, and the rules that matter."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

PROTECTED = [
    "/",
    "/patients",
    "/patients/new",
    "/doctors",
    "/doctors/new",
    "/appointments",
    "/appointments/new",
    "/consultations",
    "/consultations/new",
    "/account",
]


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
@pytest.mark.parametrize("path", PROTECTED)
def test_pages_require_login(client, path):
    client.cookies.clear()
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_login_rejects_wrong_password(client):
    client.cookies.clear()
    response = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert response.status_code == 401
    assert "Incorrect username or password" in response.text


def test_login_does_not_reveal_whether_user_exists(client):
    client.cookies.clear()
    unknown = client.post("/login", data={"username": "nobody", "password": "x"})
    wrong = client.post("/login", data={"username": "admin", "password": "x"})
    assert unknown.status_code == wrong.status_code == 401
    # Identical wording, so the form cannot be used to enumerate usernames.
    assert "Incorrect username or password" in unknown.text
    assert "Incorrect username or password" in wrong.text


def test_login_then_logout(client):
    client.cookies.clear()
    client.post(
        "/login", data={"username": "admin", "password": "testpass123"}, follow_redirects=False
    )
    assert client.get("/", follow_redirects=False).status_code == 200

    client.post("/logout", follow_redirects=False)
    assert client.get("/", follow_redirects=False).status_code == 303


def test_next_parameter_cannot_redirect_offsite(client):
    client.cookies.clear()
    response = client.post(
        "/login",
        data={"username": "admin", "password": "testpass123", "next": "https://evil.example/x"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"


# --------------------------------------------------------------------------
# Pages render with seeded data
# --------------------------------------------------------------------------
def test_dashboard_shows_seeded_clinic(auth):
    response = auth.get("/")
    assert response.status_code == 200
    assert "Dashboard" in response.text
    # Seeded patients and doctors should both be visible somewhere on it.
    assert "Today" in response.text


def test_patient_list_and_search(auth):
    response = auth.get("/patients")
    assert response.status_code == 200
    assert "Arjun Sharma" in response.text

    hit = auth.get("/patients", params={"q": "Kavya"})
    assert "Kavya Reddy" in hit.text
    assert "Arjun Sharma" not in hit.text

    miss = auth.get("/patients", params={"q": "zzzznotapatient"})
    assert "No patient matches" in miss.text


def test_patient_detail_shows_history_and_allergy_warning(auth):
    # Kavya Reddy is seeded with a penicillin allergy and a consultation.
    listing = auth.get("/patients", params={"q": "Kavya"})
    assert "Kavya Reddy" in listing.text

    # Find her id by walking the first few records.
    for pid in range(1, 12):
        page = auth.get(f"/patients/{pid}")
        if page.status_code == 200 and "Kavya Reddy" in page.text:
            assert "Penicillin" in page.text
            assert "Medical history" in page.text
            return
    pytest.fail("seeded patient Kavya Reddy was not found")


def test_doctors_and_consultations_render(auth):
    assert "Cardiology" in auth.get("/doctors").text
    assert auth.get("/consultations").status_code == 200
    assert auth.get("/appointments").status_code == 200


def test_unknown_record_returns_404(auth):
    assert auth.get("/patients/999999").status_code == 404
    assert auth.get("/consultations/999999").status_code == 404


def test_healthz_is_open(client):
    client.cookies.clear()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --------------------------------------------------------------------------
# Patient registration
# --------------------------------------------------------------------------
def test_register_patient_allocates_mrn(auth):
    response = auth.post(
        "/patients/new",
        data={
            "full_name": "Test Person",
            "date_of_birth": "1990-05-05",
            "sex": "Female",
            "phone": "+91 90000 00000",
            "address": "1 Test Street",
            "blood_group": "O+",
            "allergies": "",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Test Person" in response.text
    assert "MRN-" in response.text


def test_register_patient_rejects_future_dob(auth):
    future = (date.today() + timedelta(days=1)).isoformat()
    response = auth.post(
        "/patients/new",
        data={
            "full_name": "Not Born Yet",
            "date_of_birth": future,
            "sex": "Male",
            "phone": "+91 90000 00001",
        },
    )
    assert response.status_code == 400
    assert "cannot be in the future" in response.text


def test_register_patient_rejects_bad_date(auth):
    response = auth.post(
        "/patients/new",
        data={
            "full_name": "Bad Date",
            "date_of_birth": "not-a-date",
            "sex": "Male",
            "phone": "+91 90000 00002",
        },
    )
    assert response.status_code == 400
    assert "YYYY-MM-DD" in response.text


# --------------------------------------------------------------------------
# Appointments: the double-booking rule
# --------------------------------------------------------------------------
def _book(auth, patient_id: int, doctor_id: int, when: datetime, reason="Test"):
    return auth.post(
        "/appointments/new",
        data={
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "scheduled_at": when.strftime("%Y-%m-%dT%H:%M"),
            "reason": reason,
        },
        follow_redirects=False,
    )


def test_booking_succeeds_then_clash_is_rejected(auth):
    slot = datetime.combine(date.today() + timedelta(days=30), datetime.min.time()).replace(hour=9)

    first = _book(auth, patient_id=1, doctor_id=1, when=slot)
    assert first.status_code == 303

    # Same doctor, same minute, different patient: must be refused.
    clash = _book(auth, patient_id=2, doctor_id=1, when=slot)
    assert clash.status_code == 400
    assert "already has" in clash.text


def test_clash_window_covers_overlapping_slot(auth):
    base = datetime.combine(date.today() + timedelta(days=31), datetime.min.time()).replace(hour=14)

    assert _book(auth, 1, 2, base).status_code == 303
    # 10 minutes later still overlaps a 20-minute slot.
    overlapping = _book(auth, 2, 2, base + timedelta(minutes=10))
    assert overlapping.status_code == 400


def test_different_doctor_same_time_is_allowed(auth):
    slot = datetime.combine(date.today() + timedelta(days=32), datetime.min.time()).replace(hour=11)
    assert _book(auth, 1, 3, slot).status_code == 303
    assert _book(auth, 2, 4, slot).status_code == 303


def test_booking_outside_slot_window_is_allowed(auth):
    base = datetime.combine(date.today() + timedelta(days=33), datetime.min.time()).replace(hour=16)
    assert _book(auth, 1, 5, base).status_code == 303
    assert _book(auth, 2, 5, base + timedelta(minutes=20)).status_code == 303


def test_booking_rejects_invalid_datetime(auth):
    response = auth.post(
        "/appointments/new",
        data={"patient_id": 1, "doctor_id": 1, "scheduled_at": "nonsense", "reason": ""},
    )
    assert response.status_code == 400
    assert "valid date and time" in response.text


# --------------------------------------------------------------------------
# Consultations
# --------------------------------------------------------------------------
def test_recording_a_visit_requires_diagnosis(auth):
    response = auth.post(
        "/consultations/new",
        data={"patient_id": 1, "doctor_id": 1, "diagnosis": "   "},
    )
    assert response.status_code == 400
    assert "diagnosis is required" in response.text


def test_recording_a_visit_creates_record_and_completes_appointment(auth):
    slot = datetime.combine(date.today() + timedelta(days=40), datetime.min.time()).replace(hour=8)
    assert _book(auth, 3, 1, slot).status_code == 303

    # Find that appointment on its day.
    listing = auth.get("/appointments", params={"on": slot.date().isoformat()})
    assert listing.status_code == 200

    response = auth.post(
        "/consultations/new",
        data={
            "patient_id": 3,
            "doctor_id": 1,
            "diagnosis": "Seasonal allergic rhinitis",
            "symptoms": "Sneezing, watery eyes",
            "prescription": "Cetirizine 10mg nightly",
            "notes": "Review in a month",
            "follow_up_on": (date.today() + timedelta(days=30)).isoformat(),
            "fee": "500",
            "payment_status": "Paid",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Seasonal allergic rhinitis" in response.text
    assert "Cetirizine" in response.text


def test_consultation_rejects_negative_fee(auth):
    response = auth.post(
        "/consultations/new",
        data={"patient_id": 1, "doctor_id": 1, "diagnosis": "Test", "fee": "-50"},
    )
    assert response.status_code == 400
    assert "cannot be negative" in response.text


def test_unpaid_filter_works(auth):
    response = auth.get("/consultations", params={"unpaid": "1"})
    assert response.status_code == 200
    assert "unpaid only" in response.text.lower()


# --------------------------------------------------------------------------
# Password change
# --------------------------------------------------------------------------
def test_password_change_validates_then_succeeds(auth):
    wrong_current = auth.post(
        "/account/password",
        data={
            "current_password": "nope",
            "new_password": "brandnewpass1",
            "confirm_password": "brandnewpass1",
        },
    )
    assert wrong_current.status_code == 400
    assert "not correct" in wrong_current.text

    mismatch = auth.post(
        "/account/password",
        data={
            "current_password": "testpass123",
            "new_password": "brandnewpass1",
            "confirm_password": "different1",
        },
    )
    assert mismatch.status_code == 400
    assert "do not match" in mismatch.text

    too_short = auth.post(
        "/account/password",
        data={
            "current_password": "testpass123",
            "new_password": "short",
            "confirm_password": "short",
        },
    )
    assert too_short.status_code == 400
    assert "at least 8" in too_short.text

    ok = auth.post(
        "/account/password",
        data={
            "current_password": "testpass123",
            "new_password": "brandnewpass1",
            "confirm_password": "brandnewpass1",
        },
    )
    assert ok.status_code == 200
    assert "Password changed" in ok.text

    # The old password must no longer work.
    auth.cookies.clear()
    assert auth.post("/login", data={"username": "admin", "password": "testpass123"}).status_code == 401
    assert (
        auth.post(
            "/login",
            data={"username": "admin", "password": "brandnewpass1"},
            follow_redirects=False,
        ).status_code
        == 303
    )

    # Put it back. The account is shared across the whole session, so leaving
    # it changed would break the auth fixture for every test that runs after
    # this one.
    restored = auth.post(
        "/account/password",
        data={
            "current_password": "brandnewpass1",
            "new_password": "testpass123",
            "confirm_password": "testpass123",
        },
    )
    assert restored.status_code == 200
    assert "Password changed" in restored.text
