import type { ReactNode } from "react";
import { slug } from "../lib/format";

export function Alert({
  kind,
  children,
}: {
  kind: "error" | "warn" | "ok";
  children: ReactNode;
}) {
  return <p className={`alert ${kind}`}>{children}</p>;
}

export function Pill({ status }: { status: string }) {
  return <span className={`pill s-${slug(status)}`}>{status}</span>;
}

export function Card({
  title,
  children,
  className = "",
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {title ? <h2>{title}</h2> : null}
      {children}
    </section>
  );
}

export function PageHead({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle ? <p className="muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="actions">{actions}</div> : null}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return <p className="empty">{label}</p>;
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {hint ? <p className="hint">{hint}</p> : null}
    </div>
  );
}

/** Renders stored newlines as separate lines without using innerHTML. */
export function MultiLine({ text }: { text: string | null | undefined }) {
  if (!text || !text.trim()) return <>—</>;
  return (
    <>
      {text.split("\n").map((line, i) => (
        <span key={i}>
          {line}
          {i < text.split("\n").length - 1 ? <br /> : null}
        </span>
      ))}
    </>
  );
}
