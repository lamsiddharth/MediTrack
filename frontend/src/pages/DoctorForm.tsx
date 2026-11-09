import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { Doctor } from "../lib/types";
import { Alert, Card, Field, PageHead, Spinner } from "../components/ui";

const BLANK = {
  full_name: "",
  specialisation: "",
  phone: "",
  room: "",
  consultation_fee: "0",
};

export default function DoctorForm() {
  const { id } = useParams();
  const editing = Boolean(id);
  const navigate = useNavigate();

  const [form, setForm] = useState(BLANK);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(editing);

  useEffect(() => {
    if (!editing) return;
    api
      .get<Doctor[]>("/doctors")
      .then((list) => {
        const d = list.find((x) => String(x.id) === id);
        if (!d) throw new Error("Doctor not found.");
        setForm({
          full_name: d.full_name,
          specialisation: d.specialisation,
          phone: d.phone ?? "",
          room: d.room ?? "",
          consultation_fee: String(Math.round(Number(d.consultation_fee))),
        });
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [editing, id]);

  const set = (k: keyof typeof BLANK) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body = {
      ...form,
      phone: form.phone || null,
      room: form.room || null,
      consultation_fee: form.consultation_fee || "0",
    };
    try {
      if (editing) await api.put<Doctor>(`/doctors/${id}`, body);
      else await api.post<Doctor>("/doctors", body);
      navigate("/doctors");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Spinner />;

  return (
    <>
      <PageHead title={editing ? "Edit doctor" : "Add doctor"} />
      {error ? <Alert kind="error">{error}</Alert> : null}
      <Card>
        <form onSubmit={submit}>
          <div className="grid2">
            <Field label="Full name">
              <input required value={form.full_name} onChange={set("full_name")} />
            </Field>
            <Field label="Specialisation">
              <input required value={form.specialisation} onChange={set("specialisation")} />
            </Field>
            <Field label="Room">
              <input value={form.room} onChange={set("room")} />
            </Field>
            <Field label="Phone">
              <input value={form.phone} onChange={set("phone")} />
            </Field>
            <Field label="Consultation fee">
              <input
                type="number"
                min="0"
                step="1"
                value={form.consultation_fee}
                onChange={set("consultation_fee")}
              />
            </Field>
          </div>
          <div className="form-actions">
            <button type="submit" className="primary" disabled={busy}>
              {busy ? "Saving…" : editing ? "Save changes" : "Add doctor"}
            </button>
            <Link className="btn ghost" to="/doctors">
              Cancel
            </Link>
          </div>
        </form>
      </Card>
    </>
  );
}
