import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { Dashboard as DashboardData } from "../lib/types";
import { fmtDate, fmtDateTime, fmtLongDate, fmtTime, money, orDash } from "../lib/format";
import { Alert, Card, Empty, PageHead, Pill, Spinner } from "../components/ui";

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<DashboardData>("/dashboard")
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <Alert kind="error">{error}</Alert>;
  if (!data) return <Spinner />;

  const s = data.stats;
  const tiles = [
    { to: "/patients", n: s.patients, l: "Patients" },
    { to: "/appointments", n: s.today_total, l: "Today's appointments" },
    { to: "/appointments", n: s.today_waiting, l: "Still to be seen" },
    { to: "/consultations", n: s.consultations, l: "Records" },
    { to: "/doctors", n: s.doctors, l: "Doctors" },
    { to: "/consultations?unpaid=1", n: money(s.outstanding), l: "Outstanding", warn: true },
  ];

  return (
    <>
      <PageHead
        title="Dashboard"
        subtitle={fmtLongDate(data.today)}
        actions={
          <>
            <Link className="btn primary" to="/appointments/new">
              Book appointment
            </Link>
            <Link className="btn" to="/patients/new">
              Register patient
            </Link>
          </>
        }
      />

      <div className="stats">
        {tiles.map((t) => (
          <Link key={t.l} className={`stat ${t.warn && Number(s.outstanding) > 0 ? "warn" : ""}`} to={t.to}>
            <span className="n">{t.n}</span>
            <span className="l">{t.l}</span>
          </Link>
        ))}
      </div>

      <Card title="Today's schedule">
        {data.todays.length === 0 ? (
          <Empty>Nothing booked for today.</Empty>
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
              {data.todays.map((a) => (
                <tr key={a.id}>
                  <td className="nowrap">{fmtTime(a.scheduled_at)}</td>
                  <td>
                    <Link to={`/patients/${a.patient.id}`}>{a.patient.full_name}</Link>
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
                  <td className="right">
                    {a.status === "Scheduled" ? (
                      <Link className="btn small" to={`/consultations/new?appointment_id=${a.id}`}>
                        Record visit
                      </Link>
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

      <div className="two-col">
        <Card title="Coming up">
          {data.upcoming.length === 0 ? (
            <Empty>No future appointments booked.</Empty>
          ) : (
            <ul className="list">
              {data.upcoming.map((a) => (
                <li key={a.id}>
                  <span className="when">{fmtDateTime(a.scheduled_at)}</span>
                  <Link to={`/patients/${a.patient.id}`}>{a.patient.full_name}</Link>
                  <span className="muted small">with {a.doctor.full_name}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Recent records">
          {data.recent.length === 0 ? (
            <Empty>No consultations recorded yet.</Empty>
          ) : (
            <ul className="list">
              {data.recent.map((c) => (
                <li key={c.id}>
                  <span className="when">{fmtDate(c.visited_at)}</span>
                  <Link to={`/consultations/${c.id}`}>{c.patient_name}</Link>
                  <span className="muted small">{c.diagnosis.slice(0, 44)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
