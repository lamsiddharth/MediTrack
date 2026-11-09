import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "./lib/auth";
import Layout from "./components/Layout";
import { Spinner } from "./components/ui";

import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Patients from "./pages/Patients";
import PatientDetail from "./pages/PatientDetail";
import PatientForm from "./pages/PatientForm";
import Doctors from "./pages/Doctors";
import DoctorForm from "./pages/DoctorForm";
import Appointments from "./pages/Appointments";
import AppointmentForm from "./pages/AppointmentForm";
import Consultations from "./pages/Consultations";
import ConsultationDetail from "./pages/ConsultationDetail";
import ConsultationForm from "./pages/ConsultationForm";
import Account from "./pages/Account";

/** Gate: anything inside requires a session. */
function Protected({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <main className="centered">
        <Spinner label="Checking your session…" />
      </main>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/*"
        element={
          <Protected>
            <Layout>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/patients" element={<Patients />} />
                <Route path="/patients/new" element={<PatientForm />} />
                <Route path="/patients/:id" element={<PatientDetail />} />
                <Route path="/patients/:id/edit" element={<PatientForm />} />
                <Route path="/doctors" element={<Doctors />} />
                <Route path="/doctors/new" element={<DoctorForm />} />
                <Route path="/doctors/:id/edit" element={<DoctorForm />} />
                <Route path="/appointments" element={<Appointments />} />
                <Route path="/appointments/new" element={<AppointmentForm />} />
                <Route path="/consultations" element={<Consultations />} />
                <Route path="/consultations/new" element={<ConsultationForm />} />
                <Route path="/consultations/:id" element={<ConsultationDetail />} />
                <Route path="/account" element={<Account />} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </Layout>
          </Protected>
        }
      />
    </Routes>
  );
}

function NotFound() {
  return (
    <section className="card">
      <h1>Not found</h1>
      <p className="muted">That page does not exist.</p>
    </section>
  );
}
