import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { Patient } from "../lib/types";
import { useMeta } from "../lib/auth";
import { Alert, Card, Field, PageHead, Spinner } from "../components/ui";

const BLANK = {
  full_name: "",
  date_of_birth: "",
  sex: "Male",
  phone: "",
  address: "",
  blood_group: "",
  allergies: "",
};

export default function PatientForm() {
  const { id } = useParams();
  const editing = Boolean(id);
  const navigate = useNavigate();
  const meta = useMeta();

  const [form, setForm] = useState(BLANK);
  const [mrn, setMrn] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(editing);

  useEffect(() => {
    if (!editing) return;
    api
      .get<Patient>(`/patients/${id}`)
      .then((p) => {
        setMrn(p.mrn);
        setForm({
          full_name: p.full_name,
          date_of_birth: p.date_of_birth,
          sex: p.sex,
          phone: p.phone,
          address: p.address ?? "",
          blood_group: p.blood_group ?? "",
          allergies: p.allergies ?? "",
        });
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [editing, id]);

  const set = (k: keyof typeof BLANK) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm({ ...form, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body = {
      ...form,
      address: form.address || null,
      blood_group: form.blood_group || null,
      allergies: form.allergies || null,
    };
    try {
      const saved = editing
        ? await api.put<Patient>(`/patients/${id}`, body)
        : await api.post<Patient>("/patients", body);
      navigate(`/patients/${saved.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Spinner />;

  return (
    <>
      <PageHead
        title={editing ? "Edit patient" : "Register patient"}
        subtitle={mrn ? <span className="mono">{mrn}</span> : undefined}
      />

      {error ? <Alert kind="error">{error}</Alert> : null}

      <Card>
        <form onSubmit={submit}>
          <div className="grid2">
            <Field label="Full name">
              <input required value={form.full_name} onChange={set("full_name")} />
            </Field>
            <Field label="Phone">
              <input required value={form.phone} onChange={set("phone")} />
            </Field>
            <Field label="Date of birth">
              <input
                type="date"
                required
                value={form.date_of_birth}
                onChange={set("date_of_birth")}
              />
            </Field>
            <Field label="Sex">
              <select value={form.sex} onChange={set("sex")}>
                {meta.sexes.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Blood group">
              <input
                value={form.blood_group}
                onChange={set("blood_group")}
                placeholder="e.g. O+"
              />
            </Field>
            <Field label="Address">
              <input value={form.address} onChange={set("address")} />
            </Field>
          </div>

          <Field label="Known allergies" hint="Leave blank if none.">
            <textarea rows={2} value={form.allergies} onChange={set("allergies")} />
          </Field>

          <div className="form-actions">
            <button type="submit" className="primary" disabled={busy}>
              {busy ? "Saving…" : editing ? "Save changes" : "Register patient"}
            </button>
            <Link className="btn ghost" to={editing ? `/patients/${id}` : "/patients"}>
              Cancel
            </Link>
          </div>
        </form>
      </Card>
    </>
  );
}
