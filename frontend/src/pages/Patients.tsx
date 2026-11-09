import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import type { PatientList } from "../lib/types";
import { orDash } from "../lib/format";
import { Alert, Card, Empty, PageHead, Spinner } from "../components/ui";

export default function Patients() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const page = Number(params.get("page") ?? 1);

  const [term, setTerm] = useState(q);
  const [data, setData] = useState<PatientList | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    api
      .get<PatientList>(`/patients?q=${encodeURIComponent(q)}&page=${page}`)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [q, page]);

  function search(e: React.FormEvent) {
    e.preventDefault();
    // Reset to page 1 whenever the term changes.
    setParams(term ? { q: term } : {});
  }

  return (
    <>
      <PageHead
        title="Patients"
        subtitle={
          data ? `${data.total} registered${q ? ` · matching “${q}”` : ""}` : undefined
        }
        actions={
          <Link className="btn primary" to="/patients/new">
            Register patient
          </Link>
        }
      />

      <form className="searchbar" onSubmit={search}>
        <input
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          placeholder="Search by name, MRN or phone"
        />
        <button className="btn">Search</button>
        {q ? (
          <button
            type="button"
            className="btn ghost"
            onClick={() => {
              setTerm("");
              setParams({});
            }}
          >
            Clear
          </button>
        ) : null}
      </form>

      {error ? <Alert kind="error">{error}</Alert> : null}

      <Card>
        {!data ? (
          <Spinner />
        ) : data.items.length === 0 ? (
          <Empty>{q ? `No patient matches “${q}”.` : "No patients registered yet."}</Empty>
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th>MRN</th>
                  <th>Name</th>
                  <th>Age</th>
                  <th>Sex</th>
                  <th>Phone</th>
                  <th>Blood</th>
                  <th>Allergies</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((p) => (
                  <tr key={p.id}>
                    <td className="mono nowrap">{p.mrn}</td>
                    <td>
                      <Link to={`/patients/${p.id}`}>{p.full_name}</Link>
                    </td>
                    <td>{p.age}</td>
                    <td>{p.sex}</td>
                    <td className="nowrap">{p.phone}</td>
                    <td>{orDash(p.blood_group)}</td>
                    <td>
                      {p.allergies ? (
                        <span className="pill warn">{p.allergies}</span>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {page > 1 || data.has_next ? (
              <div className="pager">
                {page > 1 ? (
                  <Link
                    className="btn small"
                    to={`/patients?q=${encodeURIComponent(q)}&page=${page - 1}`}
                  >
                    Previous
                  </Link>
                ) : null}
                <span className="muted small">Page {page}</span>
                {data.has_next ? (
                  <Link
                    className="btn small"
                    to={`/patients?q=${encodeURIComponent(q)}&page=${page + 1}`}
                  >
                    Next
                  </Link>
                ) : null}
              </div>
            ) : null}
          </>
        )}
      </Card>
    </>
  );
}
