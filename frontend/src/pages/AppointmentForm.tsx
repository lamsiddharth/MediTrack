import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import type { Doctor, PatientList } from "../lib/types";
import { Alert, Card, Field, PageHead, Spinner } from "../components/ui";

export default function AppointmentForm() {
  const navigate = useNavigate();
  const [params] = useSearchParams();

  const [patients, setPatients] = useState<PatientList | null>(null);
  const [doctors, setDoctors] = useState<Doctor[] | null>(null);
  const [form, setForm] = useState({
    patient_id: params.get("patient_id") ?? "",
    doctor_id: "",
    scheduled_at: "",
    reason: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([
      api.get<PatientList>("/patients?page=1"),
      api.get<Doctor[]>("/doctors"),
    ])
      .then(([p, d]) => {
        setPatients(p);
        setDoctors(d);
      })
      .catch((e) => setError(e.message));
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/appointments", {
        patient_id: Number(form.patient_id),
        doctor_id: Number(form.doctor_id),
        // datetime-local gives "YYYY-MM-DDTHH:MM", which the API parses.
        scheduled_at: form.scheduled_at,
        reason: form.reason || null,
      });
      navigate(`/appointments?on=${form.scheduled_at.slice(0, 10)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not book.");
    } finally {
      setBusy(false);
    }
  }

  if (!patients || !doctors) return <Spinner />;

  return (
    <>
      <PageHead title="Book appointment" />
      {error ? <Alert kind="error">{error}</Alert> : null}

      <Card>
        <form onSubmit={submit}>
          <div className="grid2">
            <Field label="Patient">
              <select
                required
                value={form.patient_id}
                onChange={(e) => setForm({ ...form, patient_id: e.target.value })}
              >
                <option value="">Select a patient…</option>
                {patients.items.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.full_name} ({p.mrn})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Doctor">
              <select
                required
                value={form.doctor_id}
                onChange={(e) => setForm({ ...form, doctor_id: e.target.value })}
              >
                <option value="">Select a doctor…</option>
                {doctors.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.full_name} — {d.specialisation}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Date and time">
              <input
                type="datetime-local"
                required
                value={form.scheduled_at}
                onChange={(e) => setForm({ ...form, scheduled_at: e.target.value })}
              />
            </Field>
            <Field label="Reason">
              <input
                value={form.reason}
                onChange={(e) => setForm({ ...form, reason: e.target.value })}
                placeholder="e.g. Persistent cough"
              />
            </Field>
          </div>
          <div className="form-actions">
            <button type="submit" className="primary" disabled={busy}>
              {busy ? "Booking…" : "Book appointment"}
            </button>
            <Link className="btn ghost" to="/appointments">
              Cancel
            </Link>
          </div>
        </form>
      </Card>

      {patients.items.length === 0 || doctors.length === 0 ? (
        <Alert kind="warn">
          {patients.items.length === 0 ? (
            <>
              You need at least one <Link to="/patients/new">registered patient</Link>.{" "}
            </>
          ) : null}
          {doctors.length === 0 ? (
            <>
              You need at least one <Link to="/doctors/new">doctor on the roster</Link>.
            </>
          ) : null}
        </Alert>
      ) : null}
    </>
  );
}
