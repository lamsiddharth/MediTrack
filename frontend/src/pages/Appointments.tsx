import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import type { Appointment } from "../lib/types";
import { addDays, fmtDate, fmtLongDate, fmtTime, isoDay, orDash } from "../lib/format";
import { useMeta } from "../lib/auth";
import { Alert, Card, Empty, PageHead, Pill, Spinner } from "../components/ui";

export default function Appointments() {
  const meta = useMeta();
  const [params, setParams] = useSearchParams();
  const today = isoDay(new Date());
  const day = params.get("on") ?? today;
  const status = params.get("status") ?? "";

  const [rows, setRows] = useState<Appointment[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setRows(null);
    api
      .get<Appointment[]>(`/appointments?on=${day}&status=${encodeURIComponent(status)}`)
      .then(setRows)
      .catch((e) => setError(e.message));
  }, [day, status]);

  useEffect(load, [load]);

  async function setStatus(id: number, value: string) {
    setError(null);
    try {
      await api.patch(`/appointments/${id}/status`, { status: value });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update.");
    }
  }

  function go(nextDay: string, nextStatus = status) {
    const next: Record<string, string> = {};
    if (nextDay !== today) next.on = nextDay;
    if (nextStatus) next.status = nextStatus;
    setParams(next);
  }

  return (
    <>
      <PageHead
        title="Appointments"
        subtitle={`${fmtLongDate(day)}${day === today ? " · today" : ""}`}
        actions={
          <Link className="btn primary" to="/appointments/new">
            Book appointment
          </Link>
        }
      />

      <div className="daynav">
        <button className="btn small" onClick={() => go(addDays(day, -1))}>
          ← {fmtDate(addDays(day, -1))}
        </button>
        <button
          className={`btn small ${day === today ? "ghost" : ""}`}
          onClick={() => go(today)}
        >
          Today
        </button>
        <button className="btn small" onClick={() => go(addDays(day, 1))}>
          {fmtDate(addDays(day, 1))} →
        </button>

        <select value={status} onChange={(e) => go(day, e.target.value)}>
          <option value="">All statuses</option>
          {meta.appointment_statuses.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {error ? <Alert kind="error">{error}</Alert> : null}

      <Card>
        {!rows ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <Empty>
            Nothing booked for this day
            {status ? ` with status “${status}”` : ""}.
          </Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Patient</th>
                <th>Doctor</th>
                <th>Reason</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id}>
                  <td className="nowrap">{fmtTime(a.scheduled_at)}</td>
                  <td>
                    <Link to={`/patients/${a.patient.id}`}>{a.patient.full_name}</Link>
                    <br />
                    <span className="muted small mono">{a.patient.mrn}</span>
                  </td>
                  <td>
                    {a.doctor.full_name}
                    <br />
                    <span className="muted small">{a.doctor.specialisation}</span>
                  </td>
                  <td>{orDash(a.reason)}</td>
                  <td>
                    <Pill status={a.status} />
                  </td>
                  <td className="right nowrap">
                    {a.status === "Scheduled" ? (
                      <>
                        <Link
                          className="btn small primary"
                          to={`/consultations/new?appointment_id=${a.id}`}
                        >
                          Record visit
                        </Link>
                        <button className="btn small ghost" onClick={() => setStatus(a.id, "No show")}>
                          No show
                        </button>
                        <button className="btn small ghost" onClick={() => setStatus(a.id, "Cancelled")}>
                          Cancel
                        </button>
                      </>
                    ) : a.consultation_id ? (
                      <Link className="btn small ghost" to={`/consultations/${a.consultation_id}`}>
                        View record
                      </Link>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
