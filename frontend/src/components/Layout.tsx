import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth, useMeta } from "../lib/auth";

const NAV = [
  { to: "/", label: "Dashboard" },
  { to: "/patients", label: "Patients" },
  { to: "/appointments", label: "Appointments" },
  { to: "/consultations", label: "Records" },
  { to: "/doctors", label: "Doctors" },
];

export default function Layout({ children }: { children: ReactNode }) {
  const { user, signOut } = useAuth();
  const meta = useMeta();
  const navigate = useNavigate();

  async function handleSignOut() {
    await signOut();
    navigate("/login", { replace: true });
  }

  return (
    <>
      <header className="topbar">
        <NavLink to="/" className="brand">
          {meta.app_name}
        </NavLink>
        <nav>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) => (isActive ? "on" : "")}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="who">
          <NavLink to="/account">{user?.full_name}</NavLink>
          <button className="link" onClick={handleSignOut}>
            Sign out
          </button>
        </div>
      </header>

      <main>{children}</main>

      <footer className="foot">
        {meta.app_name} · demonstration system · synthetic data only
      </footer>
    </>
  );
}
