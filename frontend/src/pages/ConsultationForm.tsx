import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import type { Appointment, Doctor, PatientList } from "../lib/types";
import { useMeta } from "../lib/auth";
import { Alert, Card, Field, PageHead, Spinner } from "../components/ui";

export default function ConsultationForm() {
  const navigate = useNavigate();
  const meta = useMeta();
  const [params] = useSearchParams();
  const appointmentId = params.get("appointment_id");

  const [patients, setPatients] = useState<PatientList | null>(null);
  const [doctors, setDoctors] = useState<Doctor[] | null>(null);
  const [linked, setLinked] = useState<Appointment | null>(null);
  const [form, setForm] = useState({
    patient_id: params.get("patient_id") ?? "",
    doctor_id: "",
    diagnosis: "",
    symptoms: "",
    prescription: "",
    notes: "",
    follow_up_on: "",
    fee: "0",
    payment_status: "Unpaid",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    async function load() {
      const [p, d] = await Promise.all([
        api.get<PatientList>("/patients?page=1"),
        api.get<Doctor[]>("/doctors"),
      ]);
      setPatients(p);
      setDoctors(d);

      if (!appointmentId) return;
      // Find the booking on its own day so the form can be prefilled from it.
      const todayRows = await api.get<Appointment[]>("/appointments");
      let appt = todayRows.find((a) => String(a.id) === appointmentId) ?? null;
      if (!appt) {
        // Not today: search a window around today rather than adding an endpoint.
        for (let offset = -14; offset <= 14 && !appt; offset++) {
          const day = new Date();
          day.setDate(day.getDate() + offset);
          const iso = day.toISOString().slice(0, 10);
          const rows = await api.get<Appointment[]>(`/appointments?on=${iso}`);
          appt = rows.find((a) => String(a.id) === appointmentId) ?? null;
        }
      }
      if (appt) {
        setLinked(appt);
        const doctor = d.find((x) => x.id === appt!.doctor.id);
        setForm((f) => ({
          ...f,
          patient_id: String(appt!.patient.id),
          doctor_id: String(appt!.doctor.id),
          fee: doctor ? String(Math.round(Number(doctor.consultation_fee))) : f.fee,
        }));
      }
    }
    load().catch((e) => setError(e.message));
  }, [appointmentId]);

  // Picking a doctor manually pre-fills that doctor's fee.
  function pickDoctor(id: string) {
    const doctor = doctors?.find((x) => String(x.id) === id);
    setForm({
      ...form,
      doctor_id: id,
      fee: doctor ? String(Math.round(Number(doctor.consultation_fee))) : form.fee,
    });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const saved = await api.post<{ id: number }>("/consultations", {
        patient_id: Number(form.patient_id),
        doctor_id: Number(form.doctor_id),
        appointment_id: linked ? linked.id : null,
        diagnosis: form.diagnosis,
        symptoms: form.symptoms || null,
        prescription: form.prescription || null,
        notes: form.notes || null,
        follow_up_on: form.follow_up_on || null,
        fee: form.fee || "0",
        payment_status: form.payment_status,
      });
      navigate(`/consultations/${saved.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  if (!patients || !doctors) return <Spinner />;

  return (
    <>
      <PageHead
        title="Record visit"
        subtitle={
          linked
            ? `From appointment: ${linked.patient.full_name} with ${linked.doctor.full_name}`
            : undefined
        }
      />
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
              <select required value={form.doctor_id} onChange={(e) => pickDoctor(e.target.value)}>
                <option value="">Select a doctor…</option>
                {doctors.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.full_name} — {d.specialisation}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <Field label="Symptoms">
            <textarea
              rows={2}
              value={form.symptoms}
              onChange={(e) => setForm({ ...form, symptoms: e.target.value })}
              placeholder="What the patient reported"
            />
          </Field>

          <Field label="Diagnosis (required)">
            <textarea
              rows={2}
              required
              value={form.diagnosis}
              onChange={(e) => setForm({ ...form, diagnosis: e.target.value })}
            />
          </Field>

          <Field label="Prescription">
            <textarea
              rows={3}
              value={form.prescription}
              onChange={(e) => setForm({ ...form, prescription: e.target.value })}
              placeholder="One medication per line"
            />
          </Field>

          <Field label="Notes">
            <textarea
              rows={2}
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
            />
          </Field>

          <div className="grid2">
            <Field label="Follow-up date">
              <input
                type="date"
                value={form.follow_up_on}
                onChange={(e) => setForm({ ...form, follow_up_on: e.target.value })}
              />
            </Field>
            <Field label="Fee">
              <input
                type="number"
                min="0"
                step="1"
                value={form.fee}
                onChange={(e) => setForm({ ...form, fee: e.target.value })}
              />
            </Field>
            <Field label="Payment">
              <select
                value={form.payment_status}
                onChange={(e) => setForm({ ...form, payment_status: e.target.value })}
              >
                {meta.payment_statuses.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <div className="form-actions">
            <button type="submit" className="primary" disabled={busy}>
              {busy ? "Saving…" : "Save record"}
            </button>
            <Link className="btn ghost" to="/consultations">
              Cancel
            </Link>
          </div>
        </form>
      </Card>
    </>
  );
}
