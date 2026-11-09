import { useState } from "react";
import { api } from "../lib/api";
import { useAuth, useMeta } from "../lib/auth";
import { fmtDateTime } from "../lib/format";
import { Alert, Card, Field, PageHead } from "../components/ui";

export default function Account() {
  const { user, refreshUser } = useAuth();
  const meta = useMeta();
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setOk(null);

    // Checked here as well as server-side, to save a round trip.
    if (form.next !== form.confirm) {
      setError("The new passwords do not match.");
      return;
    }

    setBusy(true);
    try {
      await api.post("/auth/password", {
        current_password: form.current,
        new_password: form.next,
      });
      setForm({ current: "", next: "", confirm: "" });
      setOk("Password changed.");
      await refreshUser();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change the password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHead title="Account" subtitle={user?.username} />

      {error ? <Alert kind="error">{error}</Alert> : null}
      {ok ? <Alert kind="ok">{ok}</Alert> : null}

      <div className="two-col">
        <Card title="Details">
          <dl className="kv">
            <dt>Name</dt>
            <dd>{user?.full_name}</dd>
            <dt>Username</dt>
            <dd className="mono">{user?.username}</dd>
            <dt>Last signed in</dt>
            <dd>{fmtDateTime(user?.last_login_at)}</dd>
            <dt>Note storage</dt>
            <dd className="mono">{meta.storage_backend}</dd>
          </dl>
        </Card>

        <Card title="Change password">
          <form onSubmit={submit}>
            <Field label="Current password">
              <input
                type="password"
                autoComplete="current-password"
                required
                value={form.current}
                onChange={(e) => setForm({ ...form, current: e.target.value })}
              />
            </Field>
            <Field label="New password">
              <input
                type="password"
                autoComplete="new-password"
                minLength={8}
                required
                value={form.next}
                onChange={(e) => setForm({ ...form, next: e.target.value })}
              />
            </Field>
            <Field label="Confirm new password" hint="At least 8 characters.">
              <input
                type="password"
                autoComplete="new-password"
                minLength={8}
                required
                value={form.confirm}
                onChange={(e) => setForm({ ...form, confirm: e.target.value })}
              />
            </Field>
            <div className="form-actions">
              <button type="submit" className="primary" disabled={busy}>
                {busy ? "Changing…" : "Change password"}
              </button>
            </div>
          </form>
        </Card>
      </div>
    </>
  );
}
