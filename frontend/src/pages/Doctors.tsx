import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { Doctor } from "../lib/types";
import { money, orDash } from "../lib/format";
import { Alert, Card, Empty, PageHead, Spinner } from "../components/ui";

export default function Doctors() {
  const [doctors, setDoctors] = useState<Doctor[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<Doctor[]>("/doctors").then(setDoctors).catch((e) => setError(e.message));
  }, []);

  if (error) return <Alert kind="error">{error}</Alert>;

  return (
    <>
      <PageHead
        title="Doctors"
        subtitle={doctors ? `${doctors.length} on the roster` : undefined}
        actions={
          <Link className="btn primary" to="/doctors/new">
            Add doctor
          </Link>
        }
      />
      <Card>
        {!doctors ? (
          <Spinner />
        ) : doctors.length === 0 ? (
          <Empty>No doctors on the roster yet.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Specialisation</th>
                <th>Room</th>
                <th>Phone</th>
                <th className="right">Fee</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {doctors.map((d) => (
                <tr key={d.id}>
                  <td>{d.full_name}</td>
                  <td>{d.specialisation}</td>
                  <td>{orDash(d.room)}</td>
                  <td className="nowrap">{orDash(d.phone)}</td>
                  <td className="right">{money(d.consultation_fee)}</td>
                  <td className="right">
                    <Link className="btn small ghost" to={`/doctors/${d.id}/edit`}>
                      Edit
                    </Link>
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
