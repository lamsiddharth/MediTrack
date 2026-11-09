import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { Appointment, Consultation, Patient } from "../lib/types";
import { fmtDate, fmtDateTime, money, orDash } from "../lib/format";
import { Alert, Card, Empty, MultiLine, PageHead, Pill, Spinner } from "../components/ui";

export default function PatientDetail() {
  const { id } = useParams();
  const [patient, setPatient] = useState<Patient | null>(null);
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [consultations, setConsultations] = useState<Consultation[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.get<Patient>(`/patients/${id}`),
      api.get<Appointment[]>(`/patients/${id}/appointments`),
      api.get<Consultation[]>(`/patients/${id}/consultations`),
    ])
      .then(([p, a, c]) => {
        setPatient(p);
        setAppointments(a);
        setConsultations(c);
      })
      .catch((e) => setError(e.message));
  }, [id]);

  if (error) return <Alert kind="error">{error}</Alert>;
  if (!patient) return <Spinner />;

  return (
    <>
      <PageHead
        title={patient.full_name}
        subtitle={
          <>
            <span className="mono">{patient.mrn}</span> · {patient.age} years ·{" "}
            {patient.sex} · registered {fmtDate(patient.created_at)}
          </>
        }
        actions={
          <>
            <Link className="btn primary" to={`/appointments/new?patient_id=${patient.id}`}>
              Book appointment
            </Link>
            <Link className="btn" to={`/consultations/new?patient_id=${patient.id}`}>
              Record visit
            </Link>
            <Link className="btn ghost" to={`/patients/${patient.id}/edit`}>
              Edit
            </Link>
          </>
        }
      />

      {patient.allergies ? (
        <Alert kind="warn">
          <strong>Allergies:</strong> {patient.allergies}
        </Alert>
      ) : null}

      <div className="two-col">
        <Card title="Details">
          <dl className="kv">
            <dt>Date of birth</dt>
            <dd>{fmtDate(patient.date_of_birth)}</dd>
            <dt>Phone</dt>
            <dd>{patient.phone}</dd>
            <dt>Blood group</dt>
            <dd>{orDash(patient.blood_group)}</dd>
            <dt>Address</dt>
            <dd>{orDash(patient.address)}</dd>
            <dt>Allergies</dt>
            <dd>{patient.allergies ?? "None recorded"}</dd>
          </dl>
        </Card>

        <Card title="Appointments">
          {appointments.length === 0 ? (
            <Empty>No appointments booked.</Empty>
          ) : (
            <ul className="list">
              {appointments.map((a) => (
                <li key={a.id}>
                  <span className="when">{fmtDateTime(a.scheduled_at)}</span>
                  {a.doctor.full_name}
                  <Pill status={a.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title="Medical history">
        {consultations.length === 0 ? (
          <Empty>No consultations recorded for this patient.</Empty>
        ) : (
          consultations.map((c) => (
            <article className="record" key={c.id}>
              <header>
                <strong>{fmtDate(c.visited_at)}</strong>
                <span className="muted">
                  {c.doctor.full_name} · {c.doctor.specialisation}
                </span>
                <Link className="btn small ghost" to={`/consultations/${c.id}`}>
                  Open
                </Link>
              </header>
              <dl className="kv tight">
                {c.symptoms ? (
                  <>
                    <dt>Symptoms</dt>
                    <dd>{c.symptoms}</dd>
                  </>
                ) : null}
                <dt>Diagnosis</dt>
                <dd>{c.diagnosis}</dd>
                {c.prescription ? (
                  <>
                    <dt>Prescription</dt>
                    <dd>
                      <MultiLine text={c.prescription} />
                    </dd>
                  </>
                ) : null}
                {c.follow_up_on ? (
                  <>
                    <dt>Follow-up</dt>
                    <dd>{fmtDate(c.follow_up_on)}</dd>
                  </>
                ) : null}
                <dt>Fee</dt>
                <dd>
                  {money(c.fee)} <Pill status={c.payment_status} />
                </dd>
              </dl>
            </article>
          ))
        )}
      </Card>
    </>
  );
}
