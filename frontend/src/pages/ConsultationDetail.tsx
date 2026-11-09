import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { ConsultationDetail as Detail } from "../lib/types";
import { fmtDate, fmtDateTime, money } from "../lib/format";
import { useMeta } from "../lib/auth";
import { Alert, Card, Empty, MultiLine, PageHead, Pill, Spinner } from "../components/ui";

export default function ConsultationDetail() {
  const { id } = useParams();
  const meta = useMeta();
  const [data, setData] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .get<Detail>(`/consultations/${id}`)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [id]);

  useEffect(load, [load]);

  async function setPayment(value: string) {
    setError(null);
    try {
      await api.patch(`/consultations/${id}/payment`, { payment_status: value });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update.");
    }
  }

  if (error && !data) return <Alert kind="error">{error}</Alert>;
  if (!data) return <Spinner />;

  const maxMb = Math.round(meta.max_attachment_bytes / (1024 * 1024));
  const extensions = Object.values(meta.allowed_attachment_types).sort().join(", ");

  return (
    <>
      <PageHead
        title="Consultation record"
        subtitle={
          <>
            <Link to={`/patients/${data.patient.id}`}>{data.patient.full_name}</Link>{" "}
            <span className="mono">({data.patient.mrn})</span> ·{" "}
            {fmtDateTime(data.visited_at)} · {data.doctor.full_name},{" "}
            {data.doctor.specialisation}
          </>
        }
      />

      {error ? <Alert kind="error">{error}</Alert> : null}

      {data.patient_allergies ? (
        <Alert kind="warn">
          <strong>Allergies:</strong> {data.patient_allergies}
        </Alert>
      ) : null}

      <div className="two-col">
        <Card title="Clinical">
          <dl className="kv">
            <dt>Symptoms</dt>
            <dd>
              <MultiLine text={data.symptoms} />
            </dd>
            <dt>Diagnosis</dt>
            <dd>
              <MultiLine text={data.diagnosis} />
            </dd>
            <dt>Prescription</dt>
            <dd>
              <MultiLine text={data.prescription} />
            </dd>
            <dt>Notes</dt>
            <dd>
              <MultiLine text={data.notes} />
            </dd>
            <dt>Follow-up</dt>
            <dd>{fmtDate(data.follow_up_on)}</dd>
          </dl>
        </Card>

        <Card title="Billing">
          <dl className="kv">
            <dt>Fee</dt>
            <dd className="amount">{money(data.fee)}</dd>
            <dt>Status</dt>
            <dd>
              <Pill status={data.payment_status} />
            </dd>
          </dl>
          <div className="field">
            <label htmlFor="payment">Update payment</label>
            <select
              id="payment"
              value={data.payment_status}
              onChange={(e) => setPayment(e.target.value)}
            >
              {meta.payment_statuses.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        </Card>
      </div>

      <Card title="Session notes">
        {data.session_notes.length === 0 ? (
          <Empty>No progress notes on this session yet.</Empty>
        ) : (
          <div className="notes">
            {data.session_notes.map((n) => (
              <article className="note" key={n.id}>
                <header>
                  <strong>{n.title}</strong>
                  <span className="muted small">
                    {fmtDateTime(n.created_at)} · {n.author_name}
                  </span>
                </header>

                {n.unavailable ? (
                  <Alert kind="warn">
                    The text of this note could not be read from storage.
                  </Alert>
                ) : (
                  <p className="note-body">
                    <MultiLine text={n.body} />
                  </p>
                )}

                {n.has_attachment ? (
                  <p className="attachment">
                    <a
                      href={`/api/consultations/${data.id}/notes/${n.id}/attachment`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {n.attachment_filename}
                    </a>
                    <span className="muted small">{n.attachment_size_label}</span>
                  </p>
                ) : null}
              </article>
            ))}
          </div>
        )}

        <AddNote
          consultationId={data.id}
          maxMb={maxMb}
          extensions={extensions}
          accept={Object.keys(meta.allowed_attachment_types).join(",")}
          onAdded={load}
        />
      </Card>
    </>
  );
}

function AddNote({
  consultationId,
  maxMb,
  extensions,
  accept,
  onAdded,
}: {
  consultationId: number;
  maxMb: number;
  extensions: string;
  accept: string;
  onAdded: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);

    const form = new FormData();
    form.append("title", title);
    form.append("body", body);
    const file = fileRef.current?.files?.[0];
    if (file) form.append("attachment", file);

    try {
      await api.postForm(`/consultations/${consultationId}/notes`, form);
      setTitle("");
      setBody("");
      if (fileRef.current) fileRef.current.value = "";
      setOpen(false);
      onAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the note.");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <div className="add-note">
        <button className="btn" onClick={() => setOpen(true)}>
          + Add a note
        </button>
      </div>
    );
  }

  return (
    <div className="add-note">
      {error ? <Alert kind="error">{error}</Alert> : null}
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="note_title">Title</label>
          <input
            id="note_title"
            maxLength={120}
            required
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Telephone follow-up"
          />
        </div>
        <div className="field">
          <label htmlFor="note_body">Note</label>
          <textarea
            id="note_body"
            rows={4}
            required
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="What happened, what was advised, what changed."
          />
        </div>
        <div className="field">
          <label htmlFor="note_file">Attachment (optional)</label>
          <input id="note_file" type="file" ref={fileRef} accept={accept} />
          <p className="hint">
            Up to {maxMb} MB. Accepted: {extensions}. Stored in S3. Notes cannot be
            edited or deleted once saved.
          </p>
        </div>
        <div className="form-actions">
          <button type="submit" className="primary" disabled={busy}>
            {busy ? "Saving…" : "Save note"}
          </button>
          <button type="button" className="btn ghost" onClick={() => setOpen(false)}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
