import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import type { Consultation } from "../lib/types";
import { fmtDate, money } from "../lib/format";
import { Alert, Card, Empty, PageHead, Pill, Spinner } from "../components/ui";

export default function Consultations() {
  const [params, setParams] = useSearchParams();
  const unpaidOnly = params.get("unpaid") === "1";

  const [rows, setRows] = useState<Consultation[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRows(null);
    api
      .get<Consultation[]>(`/consultations?unpaid=${unpaidOnly}`)
      .then(setRows)
      .catch((e) => setError(e.message));
  }, [unpaidOnly]);

  return (
    <>
      <PageHead
        title="Consultation records"
        subtitle={rows ? `${rows.length} shown${unpaidOnly ? " · unpaid only" : ""}` : undefined}
        actions={
          <>
            <Link className="btn primary" to="/consultations/new">
              Record visit
            </Link>
            <button
              className="btn ghost"
              onClick={() => setParams(unpaidOnly ? {} : { unpaid: "1" })}
            >
              {unpaidOnly ? "Show all" : "Unpaid only"}
            </button>
          </>
        }
      />

      {error ? <Alert kind="error">{error}</Alert> : null}

      <Card>
        {!rows ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <Empty>{unpaidOnly ? "Nothing outstanding." : "No consultations recorded yet."}</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Patient</th>
                <th>Doctor</th>
                <th>Diagnosis</th>
                <th className="right">Fee</th>
                <th>Payment</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <td className="nowrap">{fmtDate(c.visited_at)}</td>
                  <td>
                    <Link to={`/patients/${c.patient.id}`}>{c.patient.full_name}</Link>
                  </td>
                  <td>{c.doctor.full_name}</td>
                  <td>
                    <Link to={`/consultations/${c.id}`}>{c.diagnosis.slice(0, 56)}</Link>
                  </td>
                  <td className="right">{money(c.fee)}</td>
                  <td>
                    <Pill status={c.payment_status} />
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
