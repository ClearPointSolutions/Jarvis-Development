import type { ReactNode } from "react";

export function LoadingState({
  label = "Loading Mission Control",
}: {
  label?: string;
}) {
  return (
    <div aria-live="polite" className="state-card" role="status">
      <span aria-hidden="true" className="state-spinner" />
      <p>{label}</p>
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="state-card state-card-error" role="alert">
      <span aria-hidden="true" className="state-symbol">
        !
      </span>
      <div>
        <h2>Something went wrong</h2>
        <p>{message}</p>
        {onRetry ? (
          <button
            className="button button-secondary"
            onClick={onRetry}
            type="button"
          >
            Try again
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function EmptyState({
  description,
  title,
}: {
  description: string;
  title: string;
}) {
  return (
    <section className="empty-state">
      <span aria-hidden="true" className="empty-state-mark">
        J
      </span>
      <h2>{title}</h2>
      <p>{description}</p>
    </section>
  );
}

export function DemoBadge({
  children = "Demo fixture",
}: {
  children?: ReactNode;
}) {
  return <span className="demo-badge">{children}</span>;
}

export function StatusLabel({
  label,
  tone,
}: {
  label: string;
  tone: "good" | "neutral" | "warning" | "danger";
}) {
  return (
    <span className={`status-label status-${tone}`}>
      <span aria-hidden="true" className="status-dot" />
      {label}
    </span>
  );
}
